"""
Async version of Docker managers using aiodocker and asyncio
"""

import asyncio
import logging
import os
import socket
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AsyncDockerManager(ABC):
    """Async base class for Docker container management"""

    def __init__(
        self,
        include_only: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ):
        self.include_only = include_only
        self.exclude = exclude if exclude else []
        self._self_excluded = False

    async def get_docker_statuses(self) -> Dict[str, str]:
        """Get filtered Docker container statuses"""
        # Auto-exclude self container on first call
        if not self._self_excluded:
            await self._auto_exclude_self()
            self._self_excluded = True

        all_statuses = await self.get_all_statuses()
        if self.include_only:
            return {k: v for k, v in all_statuses.items() if k in self.include_only}
        elif self.exclude:
            return {k: v for k, v in all_statuses.items() if k not in self.exclude}
        return all_statuses

    async def _auto_exclude_self(self):
        """Auto-exclude self container from monitoring"""
        try:
            # Method 1: Use hostname (usually the container name)
            hostname = socket.gethostname()

            # Method 2: Check all containers to find ourselves
            all_statuses = await self.get_all_statuses()

            # Look for containers with common self names
            possible_self_names = [
                hostname,
                "docker-status-mqtt-homeassistant",
                "docker-status-mqtt",
                "docker-status-mqtt-homea",  # Truncated version
            ]

            for name in possible_self_names:
                if name in all_statuses and name not in self.exclude:
                    self.exclude.append(name)
                    logger.info(f"Auto-excluding self container: {name}")
                    break

        except Exception as e:
            logger.debug(f"Could not auto-exclude self container: {e}")

    def is_container_included(self, container_name: str) -> bool:
        """Check if container should be included in monitoring"""
        if self.include_only:
            return container_name in self.include_only
        elif self.exclude:
            return container_name not in self.exclude
        return True

    @abstractmethod
    async def get_all_statuses(self) -> Dict[str, str]:
        """Get all container statuses"""
        pass

    async def stop_container(self, container_name: str):
        """Stop a container if it's included in monitoring"""
        if self.exclude and container_name in self.exclude:
            logger.warning(
                f"Container {container_name} will not be stopped, it's excluded"
            )
            return
        if self.include_only and container_name not in self.include_only:
            logger.warning(
                f"Container {container_name} will not be stopped, it's not included"
            )
            return
        await self._stop_container(container_name)

    @abstractmethod
    async def _stop_container(self, container_name: str):
        """Implementation-specific container stop method"""
        pass

    async def start_container(self, container_name: str):
        """Start a container if it's included in monitoring"""
        if self.exclude and container_name in self.exclude:
            logger.warning(
                f"Container {container_name} will not be started, it's excluded"
            )
            return
        if self.include_only and container_name not in self.include_only:
            logger.warning(
                f"Container {container_name} will not be started, it's not included"
            )
            return
        await self._start_container(container_name)

    @abstractmethod
    async def _start_container(self, container_name: str):
        """Implementation-specific container start method"""
        pass

    @abstractmethod
    async def get_container_status(self, container_name: str) -> str:
        """Get the status of a specific container"""
        pass

    async def close(self):
        """Clean up resources"""
        pass


class AsyncCommandExecutor(ABC):
    """Abstract base class for async command execution"""

    @abstractmethod
    async def run_command(self, command: str) -> str:
        """Execute a command asynchronously"""
        pass

    async def close(self):
        """Clean up resources"""
        pass


class AsyncSSHCommandExecutor(AsyncCommandExecutor):
    """Async SSH command executor using asyncio subprocess with SSH"""

    def __init__(self, host: str, port: int, user: str, password: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self._connection_pool = []
        self._pool_lock = asyncio.Lock()

    async def run_command(self, command: str) -> str:
        """Execute command via SSH using subprocess"""
        try:
            # Use ssh command with subprocess for simplicity
            # In production, consider using asyncssh library
            ssh_command = [
                "sshpass",
                "-p",
                self.password,
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=10",
                "-p",
                str(self.port),
                f"{self.user}@{self.host}",
                command,
            ]

            process = await asyncio.create_subprocess_exec(
                *ssh_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                raise RuntimeError(f"SSH command failed: {error_msg}")

            return stdout.decode().strip()

        except asyncio.TimeoutError:
            logger.error(f"SSH command timed out: {command}")
            raise
        except FileNotFoundError:
            logger.error(
                "sshpass not found. Please install sshpass for SSH functionality"
            )
            raise
        except Exception as e:
            logger.error(f"SSH command execution failed: {e}")
            raise

    async def close(self):
        """Clean up SSH connections"""
        # Cleanup would happen here if using persistent connections
        pass


class AsyncLocalCommandExecutor(AsyncCommandExecutor):
    """Async local command executor using asyncio subprocess"""

    async def run_command(self, command: str) -> str:
        """Execute command locally"""
        try:
            # Split command for subprocess
            cmd_parts = command.split()

            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                raise RuntimeError(f"Local command failed: {error_msg}")

            return stdout.decode().strip()

        except asyncio.TimeoutError:
            logger.error(f"Local command timed out: {command}")
            raise
        except Exception as e:
            logger.error(f"Local command execution failed: {e}")
            raise


class AsyncDockerCommandManager(AsyncDockerManager):
    """Async Docker manager using command execution"""

    def __init__(
        self,
        command_executor: AsyncCommandExecutor,
        include_only: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ):
        super().__init__(include_only, exclude)
        self.command_executor = command_executor

    async def get_all_statuses(self) -> Dict[str, str]:
        """Get all container statuses using docker ps command"""
        try:
            output = await self.command_executor.run_command(
                "docker ps -a --format '{{.Names}}:{{.State}}'"
            )
            status_dict = {}
            for line in output.splitlines():
                if ":" in line:
                    name, state = line.split(":", 1)
                    status_dict[name] = state
            return status_dict
        except Exception as e:
            logger.error(f"Failed to get container statuses: {e}")
            return {}

    async def _start_container(self, container_name: str):
        """Start a container using docker start command"""
        await self.command_executor.run_command(f"docker start {container_name}")

    async def _stop_container(self, container_name: str):
        """Stop a container using docker stop command"""
        await self.command_executor.run_command(f"docker stop {container_name}")

    async def get_container_status(self, container_name: str) -> str:
        """Get status of specific container"""
        try:
            return await self.command_executor.run_command(
                f"docker inspect --format='{{{{.State.Status}}}}' {container_name}"
            )
        except Exception as e:
            logger.error(f"Failed to get status for {container_name}: {e}")
            return "unknown"

    async def close(self):
        """Clean up command executor"""
        await self.command_executor.close()


class AsyncDockerSocketManager(AsyncDockerManager):
    """Async Docker manager using aiodocker"""

    def __init__(
        self,
        include_only: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ):
        super().__init__(include_only, exclude)
        self.client = None

    async def _ensure_client(self):
        """Ensure Docker client is initialized"""
        if self.client is None:
            try:
                import aiodocker

                self.client = aiodocker.Docker()
            except ImportError:
                raise ImportError("aiodocker is required for socket mode")

    async def get_all_statuses(self) -> Dict[str, str]:
        """Get all container statuses using aiodocker"""
        await self._ensure_client()
        try:
            containers = await self.client.containers.list(all=True)
            status_dict = {}
            for container in containers:
                info = await container.show()
                name = info["Name"].lstrip("/")  # Remove leading slash
                state = info["State"]["Status"]
                status_dict[name] = state
            return status_dict
        except Exception as e:
            logger.error(f"Failed to get container statuses: {e}")
            return {}

    async def _start_container(self, container_name: str):
        """Start a container using aiodocker"""
        await self._ensure_client()
        try:
            container = await self.client.containers.get(container_name)
            await container.start()
        except Exception as e:
            logger.error(f"Failed to start container {container_name}: {e}")
            raise

    async def _stop_container(self, container_name: str):
        """Stop a container using aiodocker"""
        await self._ensure_client()
        try:
            container = await self.client.containers.get(container_name)
            await container.stop()
        except Exception as e:
            logger.error(f"Failed to stop container {container_name}: {e}")
            raise

    async def get_container_status(self, container_name: str) -> str:
        """Get status of specific container"""
        await self._ensure_client()
        try:
            container = await self.client.containers.get(container_name)
            info = await container.show()
            return info["State"]["Status"]
        except Exception as e:
            logger.error(f"Failed to get status for {container_name}: {e}")
            return "unknown"

    async def close(self):
        """Clean up aiodocker client"""
        if self.client:
            try:
                await self.client.close()
            except Exception as e:
                logger.error(f"Error closing Docker client: {e}")
            finally:
                self.client = None
