import unittest
from unittest.mock import MagicMock, patch

import docker

from docker_manager import (
    DockerCommandManager,
    DockerSocketManager,
    LocalCommandExecutor,
    SSHCommandExecutor,
)


class TestDockerManager(unittest.TestCase):
    def test_docker_command_manager_start_container(self):
        mock_executor = MagicMock()
        manager = DockerCommandManager(mock_executor, include_only=["container1"])
        manager.start_container("container1")
        mock_executor.run_command.assert_called_once_with("docker start container1")

    def test_docker_command_manager_stop_container(self):
        mock_executor = MagicMock()
        manager = DockerCommandManager(mock_executor, exclude=["container2"])
        manager.stop_container("container1")
        mock_executor.run_command.assert_called_once_with("docker stop container1")

    def test_docker_command_manager_start_container_excluded(self):
        mock_executor = MagicMock()
        manager = DockerCommandManager(mock_executor, exclude=["container1"])
        manager.start_container("container1")
        mock_executor.run_command.assert_not_called()

    def test_docker_command_manager_stop_container_excluded(self):
        mock_executor = MagicMock()
        manager = DockerCommandManager(mock_executor, include_only=["container2"])
        manager.stop_container("container1")
        mock_executor.run_command.assert_not_called()

    @patch("docker.from_env")
    def test_docker_socket_manager_get_all_statuses(self, mock_docker):
        container1 = MagicMock(spec=docker.models.containers.Container)
        container1.name = "container1"
        container1.status = "running"
        container2 = MagicMock(spec=docker.models.containers.Container)
        container2.name = "container2"
        container2.status = "stopped"
        mock_docker.return_value.containers.list.return_value = [container1, container2]
        manager = DockerSocketManager()
        expected_statuses = {"container1": "running", "container2": "stopped"}
        self.assertEqual(manager.get_all_statuses(), expected_statuses)

    @patch("docker.from_env")
    def test_docker_socket_manager_start_container(self, mock_docker):
        mock_container = MagicMock()
        mock_docker.return_value.containers.get.return_value = mock_container
        manager = DockerSocketManager(include_only=["container1"])
        manager.start_container("container1")
        mock_container.start.assert_called_once()

    @patch("docker.from_env")
    def test_docker_socket_manager_stop_container(self, mock_docker):
        mock_container = MagicMock()
        mock_docker.return_value.containers.get.return_value = mock_container
        manager = DockerSocketManager(exclude=["container2"])
        manager.stop_container("container1")
        mock_container.stop.assert_called_once()

    @patch("docker.from_env")
    def test_docker_socket_manager_get_container_status(self, mock_docker):
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_docker.return_value.containers.get.return_value = mock_container
        manager = DockerSocketManager()
        status = manager.get_container_status("container1")
        self.assertEqual(status, "running")

    def test_ssh_command_executor(self):
        executor = SSHCommandExecutor(
            "test_host", 22, "test_user", "test_password", connect=False
        )
        with patch("paramiko.SSHClient.connect") as mock_connect:
            with patch("paramiko.SSHClient.exec_command") as mock_exec:
                mock_stdin = MagicMock()
                mock_stdout = MagicMock()
                mock_stderr = MagicMock()
                mock_stdout.read.return_value = b"test_output\n"
                mock_exec.return_value = (mock_stdin, mock_stdout, mock_stderr)
                executor.connect()
                mock_connect.assert_called_once_with(
                    "test_host", port=22, username="test_user", password="test_password"
                )
                output = executor.run_command("test_command")
                mock_exec.assert_called_once_with("test_command")
                self.assertEqual(output, "test_output")

    @patch("subprocess.run")
    def test_local_command_executor(self, mock_run):
        executor = LocalCommandExecutor()
        mock_run.return_value.stdout = "test_output\n"
        output = executor.run_command("test_command")
        mock_run.assert_called_once_with(
            "test_command", shell=True, text=True, capture_output=True
        )
        self.assertEqual(output, "test_output")


if __name__ == "__main__":
    unittest.main()
