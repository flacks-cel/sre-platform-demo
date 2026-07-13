export const BASE_URL =
  __ENV.BASE_URL || "http://host.docker.internal:8081";

export const CPU_SECONDS =
  Number.parseFloat(__ENV.CPU_SECONDS || "1");

export const TEST_PROFILE = __ENV.TEST_PROFILE || "default";