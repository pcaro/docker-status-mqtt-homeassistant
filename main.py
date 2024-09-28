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
        self.device_config = {
            "identifiers": [f"{self.prefix}containers"],
            "name": f"{config.entity_name} Containers",
            "model": "Docker Containers",
            "manufacturer": "Docker Container Manager",
        }

        self.known_docker_statuses = {}

        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.username_pw_set(config.mqtt_user, config.mqtt_password)
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
            self.known_docker_statuses = docker_statuses

            running_containers = sorted(
                [c for c in docker_statuses if docker_statuses[c].lower() == "running"]
            )
            logger.info(f"Running: {','.join(running_containers)}")

            for container_name, container_state in docker_statuses.items():
                self.update_entity_status(container_name, container_state)
                if container_name not in last_docker_statuses:
                    self.create_entity(container_name)

        except Exception as e:
            logger.error(f"Error al publicar el estado de los contenedores: {str(e)}")

    def create_entity(self, container_name):
        self.mqtt_client.publish(
            self._get_topic(container_name, "config"),
            json.dumps(
                {
                    "name": container_name,
                    "unique_id": f"{self.prefix}{container_name}",
                    "command_topic": self._get_topic(container_name, "command"),
                    "state_topic": self._get_topic(container_name, "state"),
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
        logger.debug(f"Configuración eliminada para {container_name}")

    def update_entity_status(self, container_name, container_state):
        """
        Publish the state of the container to the MQTT broker
        Possible docker ontainer states are: created, running, paused, restarting, removing, exited and dead.
        But we are only interested in running and stopped containers
        """
        state = "ON" if container_state.lower() == "running" else "OFF"
        self.mqtt_client.publish(self._get_topic(container_name, "state"), state)

    def _get_topic(self, container_name, topic):
        assert topic in ["state", "command", "config", ""]
        return f"homeassistant/switch/{self.prefix}{container_name}/{topic}"


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

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    main(args)
