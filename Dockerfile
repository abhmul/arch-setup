FROM ubuntu:18.04
ENV PATH /snap/bin:$PATH
COPY snap /usr/local/bin/snap
RUN apt-get update && \
      apt-get -y install sudo && \
      apt-get -y install snapd squashfuse fuse && \
      systemctl enable snapd
STOPSIGNAL SIGRTMIN+3
COPY . ubuntu-setup
