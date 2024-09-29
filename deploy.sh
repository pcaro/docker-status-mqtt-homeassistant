#!/bin/bash

DOCKER_USERNAME="pcarorevuelta"
IMAGE_NAME="docker-status-mqtt-homeassistant"

docker build . -t $IMAGE_NAME:latest
docker tag $IMAGE_NAME:latest $DOCKER_USERNAME/$IMAGE_NAME:latest

docker push $DOCKER_USERNAME/$IMAGE_NAME:latest

echo "Imagen subida con éxito a Docker Hub como $DOCKER_USERNAME/$IMAGE_NAME:latest"