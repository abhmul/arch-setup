# shortcuts
alias up='sudo apt update && sudo apt upgrade'

# docker
alias docker='sudo docker'
alias docker-smi='docker run --gpus all nvidia/cuda:9.2-base nvidia-smi'
alias tensorflow='docker run -it tensorflow/tensorflow:latest-gpu-jupyter bash'
