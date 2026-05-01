FROM debian:buster

ENV DEBIAN_FRONTEND=noninteractive
ENV VIDEO_PORTAL_ROOT=/home/pi/video-portal
ENV VIDEO_PORTAL_USE_SUDO=true

RUN printf '%s\n' \
        'deb http://archive.debian.org/debian buster main contrib non-free' \
        'deb http://archive.debian.org/debian-security buster/updates main contrib non-free' \
        > /etc/apt/sources.list \
    && printf '%s\n' \
        'Acquire::Check-Valid-Until "false";' \
        'Acquire::AllowInsecureRepositories "true";' \
        'Acquire::AllowDowngradeToInsecureRepositories "true";' \
        'APT::Get::AllowUnauthenticated "true";' \
        > /etc/apt/apt.conf.d/99buster-archive \
    && mkdir -p /etc/sudoers.d /etc/supervisor/conf.d

RUN useradd --create-home --shell /bin/bash pi \
    && mkdir -p /home/pi/video-portal /home/pi/videos \
    && chown -R pi:pi /home/pi

WORKDIR /home/pi/video-portal

COPY . /home/pi/video-portal
COPY docker/entrypoint.sh /usr/local/bin/video-portal-entrypoint
COPY docker/video_looper_stub.sh /usr/local/bin/video-looper-stub
COPY docker/supervisor/video-looper.conf /etc/supervisor/conf.d/video-looper.conf

RUN chmod 755 \
        /home/pi/video-portal/scripts/provision.sh \
        /usr/local/bin/video-portal-entrypoint \
        /usr/local/bin/video-looper-stub
RUN VIDEO_PORTAL_SKIP_SUPERVISOR_CONTROL=true /home/pi/video-portal/scripts/provision.sh \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 80

ENTRYPOINT ["/usr/local/bin/video-portal-entrypoint"]
