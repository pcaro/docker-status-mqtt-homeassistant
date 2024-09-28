import os
from docker_manager import (
    DockerCommandManager,
    DockerSocketManager,
    SSHCommandExecutor,
    LocalCommandExecutor,
)

UNRAID_HOST = os.getenv("UNRAID_HOST")
UNRAID_PORT = int(os.getenv("UNRAID_PORT", 22))
UNRAID_USER = os.getenv("UNRAID_USER")
UNRAID_PASSWORD = os.getenv("UNRAID_PASSWORD")
MQTT_URL = os.getenv("MQTT_URL")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
PUBLISH_INTERVAL = int(os.getenv("PUBLISH_INTERVAL", 60))
EXCLUDE_ONLY = os.getenv("EXCLUDE_ONLY")
if EXCLUDE_ONLY:
    EXCLUDE_ONLY = EXCLUDE_ONLY.split(",")

INCLUDE_ONLY = os.getenv("INCLUDE_ONLY")
if INCLUDE_ONLY:
    INCLUDE_ONLY = INCLUDE_ONLY.split(",")


class Config:
    def mode(self):
        """Return the mode of the docker manager, 'ssh', 'local' or 'socket'"""
        if UNRAID_HOST:
            return "ssh"
        else:
            return "socket"

    def get_manager(self):
        mode = self.mode()
        params = dict(exclude=EXCLUDE_ONLY, include_only=INCLUDE_ONLY)
        if mode == "ssh":
            return DockerCommandManager(
                SSHCommandExecutor(
                    UNRAID_HOST, UNRAID_PORT, UNRAID_USER, UNRAID_PASSWORD
                ),
                **params,
            )
        elif mode == "socket":
            return DockerSocketManager(**params)
        else:
            return DockerCommandManager(LocalCommandExecutor(), **params)
