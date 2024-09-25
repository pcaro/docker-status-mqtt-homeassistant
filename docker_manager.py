import logging
from abc import ABC, abstractmethod

import docker
import paramiko

logger = logging.getLogger(__name__)


class DockerManager(ABC):
    @abstractmethod
    def get_docker_statuses(self) -> dict[str, str]:
        pass

    @abstractmethod
    def start_container(self, container_name):
        pass

    @abstractmethod
    def stop_container(self, container_name):
        pass

    def close(self):
        pass

    def get_container_status(self, container_name) -> str:
        return self.get_docker_statuses().get(container_name, "Not found")


class DockerCommandManager(DockerManager):
    def __init__(self, command_executor):
        self.command_executor = command_executor

    def get_docker_statuses(self) -> dict[str, str]:
        """
        Retrieves the status of all Docker containers.

        Returns:
            A dictionary where keys are container names and values are their states.
        """
        output = self.command_executor.run_command(
            "docker ps -a --format '{{.Names}}:{{.State}}'"
        )
        status_dict = {}
        for line in output.splitlines():
            name, state = line.split(':', 1)
            status_dict[name] = state
        return status_dict

    def start_container(self, container_name):
        return self.command_executor.run_command(f"docker start {container_name}")

    def stop_container(self, container_name):
        return self.command_executor.run_command(f"docker stop {container_name}")

    def get_container_status(self, container_name):
        return self.command_executor.run_command(f"docker inspect --format='{{{{.State.Status}}}}' {container_name}")

    def close(self):
        self.command_executor.close()


class DockerSocketManager(DockerManager):
    """
    DockerSocketManager is a class that manages Docker containers using the Docker API.
    """
    def __init__(self):
        self.client = docker.from_env()

    def get_docker_statuses(self):
        containers = self.client.containers.list(all=True)
        return {c.name: c.status for c in containers}

    def start_container(self, container_name):
        container = self.client.containers.get(container_name)
        container.start()

    def stop_container(self, container_name):
        container = self.client.containers.get(container_name)
        container.stop()

    def get_container_status(self, container_name):
        container = self.client.containers.get(container_name)
        return container.status


class CommandExecutor(ABC):
    @abstractmethod
    def run_command(self, command):
        pass

    def close(self):
        pass


class SSHCommandExecutor(CommandExecutor):
    def __init__(self, host, port, user, password, connect=True):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if connect:
            self.connect()

    def connect(self):
        try:
            self.client.connect(
                self.host, port=self.port, username=self.user, password=self.password
            )
            logger.info(f"Conexión SSH establecida con {self.host}")
        except paramiko.AuthenticationException:
            logger.error("Error de autenticación SSH. Verifica las credenciales.")
            raise
        except paramiko.SSHException as ssh_ex:
            logger.error(f"Error al establecer la conexión SSH: {str(ssh_ex)}")
            raise
        except Exception as e:
            logger.error(f"Error inesperado al conectar por SSH: {str(e)}")
            raise

    def run_command(self, command):
        try:
            stdin, stdout, stderr = self.client.exec_command(command)
            return stdout.read().decode("utf-8").strip()
        except Exception as e:
            logger.error(f"Error al ejecutar el comando SSH '{command}': {str(e)}")
            raise

    def close(self):
        self.client.close()


class LocalCommandExecutor(CommandExecutor):
    def run_command(self, command):
        import subprocess

        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return result.stdout.strip()
