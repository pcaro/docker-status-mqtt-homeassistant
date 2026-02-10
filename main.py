import argparse
import json
import logging
import sys
import time

import paho.mqtt.client as mqtt

from config import Config

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

        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.username_pw_set(config.mqtt_user, config.mqtt_password)
        self.mqtt_client.will_set(self.availability_topic, "offline", retain=True)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message

        self.docker_manager = config.get_manager()

    def run(self):
        try:
            self.connect()
            self.mqtt_client.loop_start()
            while True:
                self.update_entities_and_statuses()
                time.sleep(self.config.publish_interval)
        except KeyboardInterrupt:
            logger.info("Interrupción de teclado detectada. Cerrando conexiones.")
        except Exception as e:
            logger.critical(f"Error crítico en el programa principal: {str(e)}")
        finally:
            logger.info("Cerrando conexiones")
            try:
                self.docker_manager.close()
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception as e:
                logger.error(f"Error al cerrar conexiones: {str(e)}")
            logger.info("Servicio finalizado")

    def on_connect(self, client, userdata, flags, rc, properties=None):
        logger.info(f"Conectado a MQTT con código {rc}")
        client.publish(self.availability_topic, "online", retain=True)
        # we should always subscribe from on_connect callback to be sure
        # our subscribed is persisted across reconnections.
        client.subscribe("homeassistant/switch/#")

    def on_message(self, client, userdata, msg):
        """We receive to messages types:
        - Reatined config messages, ie, homeassistant entities configuration (first messages on connect)
        - commands from Home Assistant to start or stop containers (user interaction)
        """
        topic = msg.topic
        if self.prefix not in topic:
            return

        container_name = topic.split("/")[-2].replace(self.prefix, "")

        try:
            if topic.endswith("/command"):
                command = msg.payload.decode()
                self.execute_command(command, container_name)
            elif topic.endswith("/config"):
                if container_name not in self.known_docker_statuses and msg.payload:
                    self.delete_entity(container_name)
        except Exception as e:
            logger.error(
                f"Error al ejecutar el comando {command} para {container_name}: {str(e)}"
            )

    def execute_command(self, command, container_name):
        logger.info(f"Comando recibido: {command} para {container_name}")
        if command == "ON":
            logger.info(f"Iniciando contenedor {container_name}")

            self.docker_manager.start_container(container_name)
        elif command == "OFF":
            logger.info(f"Deteniendo contenedor {container_name}")
            self.docker_manager.stop_container(container_name)
        else:
            logger.warning(f"Comando desconocido: {command} para {container_name}")
        time.sleep(1)
        container_status = self.docker_manager.get_container_status(container_name)
        if self.docker_manager.is_container_incuded(container_name):
            self.update_entity_status(container_name, container_status)
        logger.info(f"Estado actualizado para {container_name}: {container_status}")

    def connect(self):
        try:
            self.mqtt_client.connect(self.config.mqtt_server, self.config.mqtt_port, 60)
            logger.info(f"Conexión MQTT establecida con {self.config.mqtt_server}")

        except Exception as e:
            logger.error(f"Error al conectar con MQTT: {str(e)}")
            raise

    def update_entities_and_statuses(self):
        """Update docker entities states and create new entities if needed"""
        logger.info("Publicando estado de los contenedores Docker en MQTT")
        try:
            docker_statuses = self.docker_manager.get_docker_statuses()
            last_docker_statuses = self.known_docker_statuses

            running_containers = sorted(
                [c for c in docker_statuses if docker_statuses[c].lower() == "running"]
            )
            logger.info(f"Running: {','.join(running_containers)}")

            for container_name, container_state in docker_statuses.items():
                self.update_entity_status(container_name, container_state)
                if container_name not in last_docker_statuses:
                    self.create_entity(container_name)
                    if self.config.enable_metrics:
                        self.create_metric_entities(container_name)
                # Update metrics for running containers
                if container_state.lower() == "running" and self.config.enable_metrics:
                    self.update_container_metrics(container_name)
                elif (
                    container_state.lower() != "running" and self.config.enable_metrics
                ):
                    # Clean up metrics cache for stopped containers
                    if container_name in self.known_container_metrics:
                        del self.known_container_metrics[container_name]

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

    def create_entity(self, container_name):
        self.mqtt_client.publish(
            self._get_topic(container_name, "config"),
            json.dumps(
                {
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
                }
            ),
            retain=True,
        )
        logger.debug(f"Configuración publicada para {container_name}")

    def delete_entity(self, container_name):
        self.mqtt_client.publish(self._get_topic(container_name, "config"), "")
        self.mqtt_client.publish(self._get_topic(container_name, ""), "")
        if self.config.enable_metrics:
            self.delete_metric_entities(container_name)
            # Clean up metrics cache
            if container_name in self.known_container_metrics:
                del self.known_container_metrics[container_name]
        logger.debug(f"Configuración eliminada para {container_name}")

    def update_entity_status(self, container_name, container_state):
        """
        Publish the state of the container to the MQTT broker only if changed
        Possible docker container states are: created, running, paused, restarting, removing, exited and dead.
        But we are only interested in running and stopped containers
        """
        state = "ON" if container_state.lower() == "running" else "OFF"

        # Only publish if state has changed
        last_state = self.known_docker_statuses.get(container_name)
        if last_state is None or (last_state.lower() == "running") != (
            container_state.lower() == "running"
        ):
            self.mqtt_client.publish(
                self._get_topic(container_name, "state"), state, retain=True
            )
            logger.debug(f"Estado actualizado para {container_name}: {state}")

    def _get_topic(self, container_name, topic):
        assert topic in ["state", "command", "config", ""]
        return f"homeassistant/switch/{self.prefix}{container_name}/{topic}"

    def _get_sensor_topic(self, container_name, metric, topic):
        """Get MQTT topic for sensor entities"""
        assert topic in ["state", "config", ""]
        return f"homeassistant/sensor/{self.prefix}{container_name}_{metric}/{topic}"

    def create_metric_entities(self, container_name):
        """Create MQTT sensor entities for container metrics"""
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
            self.mqtt_client.publish(
                self._get_sensor_topic(container_name, metric, "config"),
                json.dumps(
                    {
                        "name": config["name"],
                        "unique_id": f"{self.prefix}{container_name}_{metric}",
                        "state_topic": self._get_sensor_topic(
                            container_name, metric, "state"
                        ),
                        "availability_topic": self.availability_topic,
                        "payload_available": "online",
                        "payload_not_available": "offline",
                        "unit_of_measurement": config["unit"],
                        "icon": config["icon"],
                        "device_class": config.get("device_class"),
                        "state_class": config.get("state_class"),
                        "device": self.device_config,
                    }
                ),
                retain=True,
            )
            logger.debug(f"Metric entity created for {container_name} - {metric}")

    def update_container_metrics(self, container_name):
        """Update container resource metrics only if changed"""
        if not self.config.enable_metrics:
            return

        stats = self.docker_manager.get_container_stats(container_name)
        if not stats:
            return

        # Get current metrics
        current_metrics = {
            "cpu": round(stats.get("cpu_percent", 0), 2),
            "memory": round(stats.get("memory_percent", 0), 2),
            "memory_usage": round(stats.get("memory_usage_mb", 0), 2),
            "network_rx": round(stats.get("network_rx_mb", 0), 2),
            "network_tx": round(stats.get("network_tx_mb", 0), 2),
            "disk_read": round(stats.get("blkio_read_mb", 0), 2),
            "disk_write": round(stats.get("blkio_write_mb", 0), 2),
        }

        # Get last known metrics for this container
        last_metrics = self.known_container_metrics.get(container_name, {})

        # Only publish metrics that have changed
        for metric, value in current_metrics.items():
            if (
                metric not in last_metrics or abs(last_metrics[metric] - value) >= 0.01
            ):  # Threshold for change
                self.mqtt_client.publish(
                    self._get_sensor_topic(container_name, metric, "state"),
                    str(value),
                    retain=True,
                )
                logger.debug(
                    f"Métrica actualizada para {container_name}.{metric}: {value}"
                )

        # Update known metrics
        self.known_container_metrics[container_name] = current_metrics

    def delete_metric_entities(self, container_name):
        """Delete MQTT sensor entities for container metrics"""
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
            self.mqtt_client.publish(
                self._get_sensor_topic(container_name, metric, "config"), ""
            )
            self.mqtt_client.publish(
                self._get_sensor_topic(container_name, metric, ""), ""
            )


def main(args):
    logger.info("Iniciando el servicio Docker Status MQTT")
    service = DockerMQTT(config=Config(**vars(args)))
    service.run()


if __name__ == "__main__":
    # Vamos a aceptar parámetros de línea de comandos para poder ejecutar el script en modo local
    # o en modo SSH
    # --verbose para activar el modo verbose (debug). Esto cambia el loggin a nivel DEBUG

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

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    main(args)
