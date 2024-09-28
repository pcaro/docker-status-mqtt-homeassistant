import os
from docker_manager import (
    DockerCommandManager,
    DockerSocketManager,
    SSHCommandExecutor,
    LocalCommandExecutor,
)

class Config:
    def __init__(
        self,
        unraid_host=None,
        unraid_port=None,
        unraid_user=None,
        unraid_password=None,
        mqtt_server=None,
        mqtt_port=None,
        mqtt_user=None,
        mqtt_password=None,
        publish_interval=None,
        exclude_only=None,
        include_only=None,
        use_cmd_local=False,
        entity_name="Unraid Docker",
        entity_prefix=None,
        verbose=False,
    ):
        self.unraid_host = unraid_host or os.getenv("SSH_HOST")
        self.unraid_port = int(unraid_port or os.getenv("SSH_PORT", 22))
        self.unraid_user = unraid_user or os.getenv("SSH_USER")
        self.unraid_password = unraid_password or os.getenv("SSH_PASSWORD")
        self.mqtt_server = mqtt_server or os.getenv("MQTT_SERVER")
        self.mqtt_port = int(mqtt_port or os.getenv("MQTT_PORT", 1883))
        self.mqtt_user = mqtt_user or os.getenv("MQTT_USER")
        self.mqtt_password = mqtt_password or os.getenv("MQTT_PASSWORD")
        self.publish_interval = int(
            publish_interval or os.getenv("PUBLISH_INTERVAL", 60)
        )
        exclude_only = exclude_only or os.getenv("EXCLUDE_ONLY")
        if exclude_only:
            self.exclude_only = exclude_only.split(",")
        else:
            self.exclude_only = None
        include_only = include_only or os.getenv("INCLUDE_ONLY")
        if include_only:
            self.include_only = include_only.split(",")
        else:
            self.include_only = None
        self.use_cmd_local = use_cmd_local
        self.entity_name = entity_name

        if entity_prefix is None:
            entity_prefix = entity_name.lower().replace(" ", "_") + "_"
        self.entity_prefix = entity_prefix

        self.verbose = verbose

        self.validate_config()

    def validate_config(self):
        if self.mode() == "ssh":
            if not self.unraid_host:
                raise ValueError("Unraid host is required for SSH mode")
            if not self.unraid_user:
                raise ValueError("Unraid user is required for SSH mode")
            if not self.unraid_password:
                raise ValueError("Unraid password is required for SSH mode")
        if not self.mqtt_server:
            raise ValueError("MQTT server is required")
        if self.exclude_only and self.include_only:
            raise ValueError("exclude_only and include_only are mutually exclusive")

    def mode(self):
        """Return the mode of the docker manager, 'ssh', 'local' or 'socket'"""
        if self.use_cmd_local:
            return "local"
        if self.unraid_host:
            return "ssh"
        return "socket"

    def get_manager(self):
        mode = self.mode()
        params = dict(exclude=self.exclude_only, include_only=self.include_only)
        if mode == "ssh":
            return DockerCommandManager(
                SSHCommandExecutor(
                    self.unraid_host, self.unraid_port, self.unraid_user, self.unraid_password
                ),
                **params,
            )
        elif mode == "socket":
            return DockerSocketManager(**params)
        else:
            return DockerCommandManager(LocalCommandExecutor(), **params)
