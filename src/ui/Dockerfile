# Reproducible browser telemetry bundle (no unpinned CDN dependency).
FROM node:22-bookworm-slim AS frontend
WORKDIR /ui/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/src ./src
RUN npm run build

# Build Stage
FROM public.ecr.aws/amazonlinux/amazonlinux:2023 AS build-env

# We tell DNF not to install Recommends and Suggests packages, keeping our
# installed set of packages as minimal as possible.
RUN dnf --setopt=install_weak_deps=False install -q -y \
    maven \
    java-21-amazon-corretto-headless \
    which \
    tar \
    gzip \
    && \
    dnf clean all

RUN curl -fsSL https://github.com/grafana/pyroscope-java/releases/download/v2.9.2/pyroscope.jar -o /pyroscope.jar \
    && echo 'ad738199a90734f7b8392bae1ab892027d411acb953ef1f00cd6e8e7c669ff8f  /pyroscope.jar' | sha256sum -c -

VOLUME /tmp
WORKDIR /

COPY .mvn .mvn
COPY mvnw .
COPY pom.xml .

RUN ./mvnw dependency:go-offline -B -q

COPY ./src ./src
COPY --from=frontend /ui/src/main/resources/static/assets/js/grot-observability.js ./src/main/resources/static/assets/js/grot-observability.js

RUN ./mvnw -DskipTests package -q && \
    mv /target/ui-0.0.1-SNAPSHOT.jar /app.jar

# Package Stage
FROM public.ecr.aws/amazonlinux/amazonlinux:2023

# Apply all available security updates before installing packages. Amazon Linux
# 2023 locks DNF to the release snapshot the base image was built from, so
# --releasever=latest is required to pick up newer patched packages.
# https://docs.aws.amazon.com/linux/al2023/ug/deterministic-upgrades-usage.html
#
# We tell DNF not to install Recommends and Suggests packages, which are
# weak dependencies in DNF terminology, thus keeping our installed set of
# packages as minimal as possible.
RUN dnf --releasever=latest upgrade -q -y \
    && \
    dnf --setopt=install_weak_deps=False install -q -y \
    java-21-amazon-corretto-headless \
    shadow-utils \
    && \
    dnf clean all

# use curl-full to use "telnet://" scheme
# https://docs.aws.amazon.com/linux/al2023/ug/curl-minimal.html
RUN dnf -q -y swap libcurl-minimal libcurl-full \
    && dnf -q -y swap curl-minimal curl-full

ENV APPUSER=appuser
ENV APPUID=1000
ENV APPGID=1000

RUN useradd \
    --home "/app" \
    --create-home \
    --user-group \
    --uid "$APPUID" \
    "$APPUSER"

ENV JAVA_TOOL_OPTIONS=
ENV SPRING_PROFILES_ACTIVE=prod

WORKDIR /app
USER appuser

COPY ./ATTRIBUTION.md ./LICENSES.md
COPY --chown=appuser:appuser --from=build-env /app.jar .
COPY --chown=appuser:appuser --from=build-env /pyroscope.jar .

EXPOSE 8080

ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/app.jar"]
