variable "GHCR_IMAGE" {
  default = "ghcr.io/jumpserver-east/component"
}

variable "ALIYUN_IMAGE" {
  default = "registry.example.com/fit2cloud_nickyang0_0/component"
}

variable "BASE_IMAGE" {
  default = "component"
}

variable "TAG" {
  default = "dev"
}

target "ce" {
  context    = "."
  dockerfile = "Dockerfile"
  args = {
    VERSION = "${TAG}"
  }
  cache-from = ["type=gha,scope=${BASE_IMAGE}-ce"]
  cache-to   = ["type=gha,mode=max,scope=${BASE_IMAGE}-ce"]
}

target "ee" {
  context    = "."
  dockerfile = "Dockerfile-ee"
  args = {
    VERSION = "${TAG}"
  }
  contexts = {
    "jumpserver/${BASE_IMAGE}:${TAG}-ce" = "target:ce"
  }
  tags = [
    "${GHCR_IMAGE}:${TAG}",
    "${ALIYUN_IMAGE}:${TAG}",
  ]
  labels = {
    "org.opencontainers.image.version" = "${TAG}"
    "org.jumpserver.edition"           = "ee"
  }
  cache-from = ["type=gha,scope=${BASE_IMAGE}-ee"]
  cache-to   = ["type=gha,mode=max,scope=${BASE_IMAGE}-ee"]
}

target "xpack-placeholder" {
  context    = ".build-config"
  dockerfile = "Dockerfile.xpack-placeholder"
}

target "ee-core" {
  inherits = ["ee"]
  contexts = {
    "registry.fit2cloud.com/jumpserver/xpack:${TAG}" = "target:xpack-placeholder"
  }
  labels = {
    "org.jumpserver.xpack" = "placeholder"
  }
}
