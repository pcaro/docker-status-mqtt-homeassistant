import argparse
import asyncio
import concurrent.futures
import json
import logging
import signal
import sys
import time

import aiomqtt
from config import Config
from web_ui import WebServer

log_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(log_formatter)

logger = logging.getLogger()
logger.addHandler(stdout_handler)
logger.setLevel(logging.INFO)


class DockerMQTT:
    def __init__(
        self,
        config: Config,
    ):
        self.config = config
        self.prefix = config.entity_prefix
        self.availability_topic = f"homeassistant/switch/{self.prefix}availability"
        self.device_config = {
            "identifiers": [f"{self.prefix}containers"],
            "name": f"{config.entity_name} Containers",
            "model": "Docker Containers",
            "manufacturer": "Docker Container Manager",
        }

        self.known_docker_statuses = {}
        self.known_container_metrics = {}  # Track last published metrics
        self.docker_manager = config.get_manager()
        self.shutdown_event = asyncio.Event()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        
        # Initialize Web Server
        self.web_server = WebServer(self, port=self.config.web_port)
        self.client = None # Client will be set in run()

    async def run(self):
        """Main async loop"""
        try:
            logger.info(f"Conectando a MQTT {self.config.mqtt_server}:{self.config.mqtt_port}")
            
            # Setup will message for LWT
            will = aiomqtt.Will(
                topic=self.availability_topic,
                payload="offline",
                qos=1,
                retain=True
            )

            async with aiomqtt.Client(
                hostname=self.config.mqtt_server,
                port=self.config.mqtt_port,
                username=self.config.mqtt_user,
                password=self.config.mqtt_password,
                will=will,
            ) as client:
                self.client = client
                logger.info("Conectado a MQTT")
                
                # Publish online status
                await client.publish(self.availability_topic, "online", retain=True)
                
                # Subscribe to commands
                await client.subscribe("homeassistant/switch/#")
                
                # Start the command listener task
                listener_task = asyncio.create_task(self.command_listener())
                
                # Start the status updater task
                updater_task = asyncio.create_task(self.status_updater())
                
                # Start Web Server task
                web_server_task = asyncio.create_task(self.web_server.start())
                
                # Wait until shutdown signal
                await self.shutdown_event.wait()
                
                logger.info("Apagando servicios...")
                listener_task.cancel()
                updater_task.cancel()
                # web_server_task needs special handling or just let loop close handle it?
                # uvicorn handles its own signals, but since we run it in a task, we might cancel it.
                # However, uvicorn.Server.serve() captures signals by default. 
                # Since we run it inside our loop, we should check uvicorn config.
                web_server_task.cancel()
                
                # Publish offline status before disconnecting
                await client.publish(self.availability_topic, "offline", retain=True)

        except aiomqtt.MqttError as e:
            logger.error(f"Error de conexión MQTT: {e}")
            # If connection fails, we might want to retry or exit. 
            # For now, let's exit so the container restarts
            sys.exit(1)
        except Exception as e:
            logger.critical(f"Error crítico: {e}")
            sys.exit(1)
        finally:
            self.docker_manager.close()
            self.executor.shutdown(wait=False)
            logger.info("Servicio finalizado")

    async def command_listener(self):
        """Listen for MQTT messages"""
        try:
            async for message in self.client.messages:
                topic = message.topic.value
                payload = message.payload.decode() if message.payload else None
                
                if self.prefix not in topic:
                    continue

                container_name = topic.split("/")[-2].replace(self.prefix, "")

                if topic.endswith("/command"):
                    await self.execute_command(payload, container_name)
                elif topic.endswith("/config"):
                    # Only delete if we are sure it's an entity we should manage but it's no longer in docker
                    # Wait for first full status update to be sure
                    if self.known_docker_statuses and container_name not in self.known_docker_statuses and payload:
                        logger.info(f"Limpiando entidad huérfana en HA: {container_name}")
                        await self.delete_entity(container_name)
                        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error en listener de comandos: {e}")

    async def execute_command(self, command, container_name):
        logger.info(f"Comando recibido: {command} para {container_name}")
        
        loop = asyncio.get_running_loop()
        
        if command == "ON":
            logger.info(f"Iniciando contenedor {container_name}")
            # Run blocking docker command in executor
            await loop.run_in_executor(
                self.executor, 
                self.docker_manager.start_container, 
                container_name
            )
        elif command == "OFF":
            logger.info(f"Deteniendo contenedor {container_name}")
            # Run blocking docker command in executor
            await loop.run_in_executor(
                self.executor, 
                self.docker_manager.stop_container, 
                container_name
            )
        else:
            logger.warning(f"Comando desconocido: {command} para {container_name}")
            return

        # Wait a bit for status change
        await asyncio.sleep(1)
        
        # Get new status (blocking)
        container_status = await loop.run_in_executor(
            self.executor,
            self.docker_manager.get_container_status,
            container_name
        )
        
        # Strip potential whitespace
        if container_status:
            container_status = container_status.strip()

        if self.docker_manager.is_container_incuded(container_name):
            # Update known status BEFORE calling update_entity_status to avoid it thinking nothing changed
            # But wait, update_entity_status uses known_docker_statuses as the OLD state.
            # So we should update it AFTER.
            await self.update_entity_status(container_name, container_status)
            self.known_docker_statuses[container_name] = container_status
            
        logger.info(f"Estado actualizado para {container_name}: {container_status}")

    async def status_updater(self):
        """Periodic status update loop"""
        try:
            while not self.shutdown_event.is_set():
                await self.update_entities_and_statuses()
                await asyncio.sleep(self.config.publish_interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error en bucle de actualización: {e}")

    async def update_entities_and_statuses(self):
        """Update docker entities states and create new entities if needed"""
        logger.info("Publicando estado de los contenedores Docker en MQTT")
        loop = asyncio.get_running_loop()
        
        try:
            # Run blocking docker operations in executor
            docker_statuses = await loop.run_in_executor(
                self.executor,
                self.docker_manager.get_docker_statuses
            )
            
            last_docker_statuses = self.known_docker_statuses.copy()

            running_containers = sorted(
                [c for c in docker_statuses if docker_statuses[c].lower() == "running"]
            )
            logger.info(f"Running: {','.join(running_containers)}")

            # Update existing and new containers
            for container_name, container_state in docker_statuses.items():
                await self.update_entity_status(container_name, container_state)
                
                if container_name not in last_docker_statuses:
                    await self.create_entity(container_name)
                    if self.config.enable_metrics:
                        await self.create_metric_entities(container_name)
                
                # Update metrics for running containers
                if container_state.lower() == "running" and self.config.enable_metrics:
                    await self.update_container_metrics(container_name)
                elif (
                    container_state.lower() != "running" and self.config.enable_metrics
                ):
                    # Clean up metrics cache for stopped containers
                    if container_name in self.known_container_metrics:
                        del self.known_container_metrics[container_name]

            # Handle containers that disappeared from Docker
            for container_name in last_docker_statuses:
                if container_name not in docker_statuses:
                    logger.info(f"Contenedor {container_name} ya no está presente, marcando como OFF")
                    await self.update_entity_status(container_name, "exited")
                    # Also delete entity from HA after a while? 
                    # For now just mark as OFF so the switch reflects reality

            # Update known statuses after processing all containers
            self.known_docker_statuses = docker_statuses


            # Update heartbeat file for health check
            self._update_heartbeat()

        except Exception as e:
            logger.error(f"Error al publicar el estado de los contenedores: {str(e)}")

    def _update_heartbeat(self):
        """Update heartbeat file for health checks"""
        try:
            import pathlib
            heartbeat_file = pathlib.Path("/tmp/docker-status-mqtt-heartbeat")
            heartbeat_file.touch()
        except Exception as e:
            logger.debug(f"Failed to update heartbeat: {e}")

    async def create_entity(self, container_name):
        payload = json.dumps({
            "name": container_name,
            "unique_id": f"{self.prefix}{container_name}",
            "command_topic": self._get_topic(container_name, "command"),
            "state_topic": self._get_topic(container_name, "state"),
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "payload_on": "ON",
            "payload_off": "OFF",
            "state_on": "ON",
            "state_off": "OFF",
            "device": self.device_config,
        })
        
        await self.client.publish(
            self._get_topic(container_name, "config"),
            payload,
            retain=True,
        )
        logger.debug(f"Configuración publicada para {container_name}")

    async def delete_entity(self, container_name):
        await self.client.publish(self._get_topic(container_name, "config"), "")
        await self.client.publish(self._get_topic(container_name, ""), "")
        
        if self.config.enable_metrics:
            await self.delete_metric_entities(container_name)
            # Clean up metrics cache
            if container_name in self.known_container_metrics:
                del self.known_container_metrics[container_name]
        logger.debug(f"Configuración eliminada para {container_name}")

    async def update_entity_status(self, container_name, container_state):
        if not container_state:
            return
            
        container_state = container_state.strip()
        state = "ON" if container_state.lower() == "running" else "OFF"

        # Only publish if state has changed
        last_state = self.known_docker_statuses.get(container_name)
        
        state_changed = last_state is None or (last_state.lower() == "running") != (
            container_state.lower() == "running"
        )
        
        if state_changed:
            topic = self._get_topic(container_name, "state")
            logger.info(f"Publicando estado para {container_name}: {state} en {topic}")
            await self.client.publish(
                topic, 
                state, 
                retain=True
            )
        else:
            logger.debug(f"Estado sin cambios para {container_name}: {state}")

    def _get_topic(self, container_name, topic):
        assert topic in ["state", "command", "config", ""]
        return f"homeassistant/switch/{self.prefix}{container_name}/{topic}"

    def _get_sensor_topic(self, container_name, metric, topic):
        assert topic in ["state", "config", ""]
        return f"homeassistant/sensor/{self.prefix}{container_name}_{metric}/{topic}"

    async def create_metric_entities(self, container_name):
        metrics_config = {
            "cpu": {
                "name": f"{container_name} CPU",
                "unit": "%",
                "icon": "mdi:cpu-64-bit",
                "device_class": None,
                "state_class": "measurement",
            },
            "memory": {
                "name": f"{container_name} Memory",
                "unit": "%",
                "icon": "mdi:memory",
                "device_class": None,
                "state_class": "measurement",
            },
            "memory_usage": {
                "name": f"{container_name} Memory Usage",
                "unit": "MB",
                "icon": "mdi:memory",
                "device_class": None,
                "state_class": "measurement",
            },
            "network_rx": {
                "name": f"{container_name} Network RX",
                "unit": "MB",
                "icon": "mdi:download-network",
                "device_class": None,
                "state_class": "total_increasing",
            },
            "network_tx": {
                "name": f"{container_name} Network TX",
                "unit": "MB",
                "icon": "mdi:upload-network",
                "device_class": None,
                "state_class": "total_increasing",
            },
            "disk_read": {
                "name": f"{container_name} Disk Read",
                "unit": "MB",
                "icon": "mdi:harddisk",
                "device_class": None,
                "state_class": "total_increasing",
            },
            "disk_write": {
                "name": f"{container_name} Disk Write",
                "unit": "MB",
                "icon": "mdi:harddisk",
                "device_class": None,
                "state_class": "total_increasing",
            },
        }

        for metric, config in metrics_config.items():
            payload = json.dumps({
                "name": config["name"],
                "unique_id": f"{self.prefix}{container_name}_{metric}",
                "state_topic": self._get_sensor_topic(container_name, metric, "state"),
                "availability_topic": self.availability_topic,
                "payload_available": "online",
                "payload_not_available": "offline",
                "unit_of_measurement": config["unit"],
                "icon": config["icon"],
                "device_class": config.get("device_class"),
                "state_class": config.get("state_class"),
                "device": self.device_config,
            })
            
            await self.client.publish(
                self._get_sensor_topic(container_name, metric, "config"),
                payload,
                retain=True,
            )
            logger.debug(f"Metric entity created for {container_name} - {metric}")

    async def update_container_metrics(self, container_name):
        if not self.config.enable_metrics:
            return

        loop = asyncio.get_running_loop()
        stats = await loop.run_in_executor(
            self.executor,
            self.docker_manager.get_container_stats,
            container_name
        )
        
        if not stats:
            return

        current_metrics = {
            "cpu": round(stats.get("cpu_percent", 0), 2),
            "memory": round(stats.get("memory_percent", 0), 2),
            "memory_usage": round(stats.get("memory_usage_mb", 0), 2),
            "network_rx": round(stats.get("network_rx_mb", 0), 2),
            "network_tx": round(stats.get("network_tx_mb", 0), 2),
            "disk_read": round(stats.get("blkio_read_mb", 0), 2),
            "disk_write": round(stats.get("blkio_write_mb", 0), 2),
        }

        last_metrics = self.known_container_metrics.get(container_name, {})

        for metric, value in current_metrics.items():
            if (
                metric not in last_metrics or abs(last_metrics[metric] - value) >= 0.01
            ):
                await self.client.publish(
                    self._get_sensor_topic(container_name, metric, "state"),
                    str(value),
                    retain=True,
                )
                logger.debug(
                    f"Métrica actualizada para {container_name}.{metric}: {value}"
                )

        self.known_container_metrics[container_name] = current_metrics

    async def delete_metric_entities(self, container_name):
        metrics = [
            "cpu",
            "memory",
            "memory_usage",
            "network_rx",
            "network_tx",
            "disk_read",
            "disk_write",
        ]
        for metric in metrics:
            await self.client.publish(
                self._get_sensor_topic(container_name, metric, "config"), ""
            )
            await self.client.publish(
                self._get_sensor_topic(container_name, metric, ""), ""
            )


def handle_shutdown(service, loop):
    logger.info("Recibida señal de parada")
    service.shutdown_event.set()

def main(args):
    logger.info("Iniciando el servicio Docker Status MQTT (Async)")
    service = DockerMQTT(config=Config(**vars(args)))
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: handle_shutdown(service, loop))
        
    try:
        loop.run_until_complete(service.run())
    finally:
        loop.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Docker Status MQTT. Only mqtt_server is required. "
        "You can use environment variables too. Just use capital letters and underscores."
    )
    parser.add_argument("--verbose", action="store_true", help="Activar modo verbose")
    parser.add_argument(
        "--name",
        dest="entity_name",
        help="Nombre del dispositivo en Home Assistant",
        default="Unraid Docker",
    )
    parser.add_argument(
        "--unraid_host",
        "-H",
        help="Host de Unraid",
        default=None,
    )
    parser.add_argument(
        "--unraid_port",
        "-p",
        help="Puerto de Unraid",
        default=None,
    )
    parser.add_argument(
        "--unraid_user",
        "-u",
        help="Usuario de Unraid",
        default=None,
    )
    parser.add_argument(
        "--unraid_password",
        help="Contraseña de Unraid",
        default=None,
    )
    parser.add_argument(
        "--mqtt_server",
        help="URL del broker MQTT",
        default=None,
    )
    parser.add_argument(
        "--mqtt_port",
        help="Puerto del broker MQTT",
        default=None,
    )
    parser.add_argument(
        "--mqtt_user",
        help="Usuario del broker MQTT",
        default=None,
    )
    parser.add_argument(
        "--mqtt_password",
        help="Contraseña del broker MQTT",
        default=None,
    )
    parser.add_argument(
        "--publish_interval",
        help="Intervalo de publicación en segundos",
        default=None,
    )
    parser.add_argument(
        "--exclude_only",
        help="Contenedores a excluir",
        default=None,
    )
    parser.add_argument(
        "--include_only",
        help="Contenedores a incluir",
        default=None,
    )
    parser.add_argument(
        "--use_cmd_local",
        help="Usar comandos locales en lugar de SSH",
        action="store_true",
    )
    parser.add_argument(
        "--entity_prefix",
        help="Prefijo de los dispositivos en Home Assistant",
        default=None,
    )
    parser.add_argument(
        "--enable_metrics",
        help="Habilitar métricas de contenedores (CPU, memoria, red, disco)",
        action="store_true",
    )
    parser.add_argument(
        "--web_port",
        help="Puerto para el servidor web",
        default=None,
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    main(args)
