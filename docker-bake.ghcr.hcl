variable "IMAGE" {
  default = "ghcr.io/jumpserver-east/web"
}

variable "TAG" {
  default = "dev"
}

variable "LINA_REF" {
  default = "dev"
}

variable "LUNA_REF" {
  default = "dev"
}

variable "WEB_REF" {
  default = "dev"
}

group "default" {
  targets = ["web"]
}

target "lina" {
  context    = "https://github.com/jumpserver-east/lina.git#${LINA_REF}"
  dockerfile = "Dockerfile"
  args = {
    VERSION = "${TAG}"
  }
  cache-from = ["type=gha,scope=web-lina"]
  cache-to   = ["type=gha,mode=max,scope=web-lina"]
}

target "luna" {
  context    = "https://github.com/jumpserver-east/luna.git#${LUNA_REF}"
  dockerfile = "Dockerfile"
  args = {
    VERSION = "${TAG}"
  }
  cache-from = ["type=gha,scope=web-luna"]
  cache-to   = ["type=gha,mode=max,scope=web-luna"]
}

target "web" {
  context    = "./web-source"
  dockerfile = "Dockerfile"
  args = {
    VERSION = "${TAG}"
  }
  contexts = {
    "jumpserver/lina:${TAG}" = "target:lina"
    "jumpserver/luna:${TAG}" = "target:luna"
  }
  tags   = ["${IMAGE}:${TAG}"]
  output = ["type=registry"]
  labels = {
    "org.opencontainers.image.title"         = "JumpServer Web"
    "org.opencontainers.image.version"       = "${TAG}"
    "org.opencontainers.image.revision"      = "${WEB_REF}"
    "org.jumpserver.image.lina.revision"      = "${LINA_REF}"
    "org.jumpserver.image.luna.revision"      = "${LUNA_REF}"
    "org.jumpserver.image.dockerweb.revision" = "${WEB_REF}"
  }
  cache-from = ["type=gha,scope=web-final"]
  cache-to   = ["type=gha,mode=max,scope=web-final"]
}
