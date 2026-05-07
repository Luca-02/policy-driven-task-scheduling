#!/bin/sh

echo "Starting cluster containers..."
docker start $(docker ps -aq --filter "name=thesis-")