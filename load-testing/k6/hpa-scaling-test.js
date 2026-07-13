import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

import {
  BASE_URL,
  CPU_SECONDS,
} from "./config.js";

const applicationErrors = new Rate("application_errors");
const cpuSimulationDuration = new Trend(
  "cpu_simulation_duration",
  true,
);

export const options = {
  scenarios: {
    hpa_scaling: {
      executor: "ramping-vus",
      startVUs: 0,
      gracefulRampDown: "10s",

      stages: [
        // Aquecimento
        { duration: "20s", target: 2 },

        // Primeira pressão sobre CPU
        { duration: "30s", target: 5 },

        // Carga suficiente para disparar o HPA
        { duration: "1m", target: 15 },

        // Sustenta a carga para permitir novas réplicas
        { duration: "2m", target: 15 },

        // Pico controlado
        { duration: "30s", target: 25 },

        // Mantém o pico
        { duration: "1m", target: 25 },

        // Redução gradual
        { duration: "30s", target: 5 },

        // Encerramento
        { duration: "20s", target: 0 },
      ],
    },
  },

  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: [
      "p(95)<5000",
      "p(99)<8000",
    ],
    application_errors: ["rate<0.05"],
  },

  tags: {
    test_type: "hpa-scaling",
    application: "jobs-api",
  },
};

export function setup() {
  const healthResponse = http.get(`${BASE_URL}/health`, {
    tags: {
      endpoint: "health",
    },
  });

  const applicationIsHealthy = check(healthResponse, {
    "application is reachable": (response) =>
      response.status === 200,
  });

  if (!applicationIsHealthy) {
    throw new Error(
      `Jobs API is unavailable at ${BASE_URL}. ` +
      `Received HTTP ${healthResponse.status}.`,
    );
  }

  console.log(
    `Starting HPA scaling test against ${BASE_URL}`,
  );

  console.log(
    `CPU simulation duration: ${CPU_SECONDS} second(s)`,
  );
}

export default function () {
  const response = http.get(
    `${BASE_URL}/simulate/cpu?seconds=${CPU_SECONDS}`,
    {
      timeout: "15s",
      tags: {
        endpoint: "simulate-cpu",
        test_type: "hpa-scaling",
      },
    },
  );

  cpuSimulationDuration.add(response.timings.duration);

  const requestSucceeded = check(response, {
    "CPU simulation returned HTTP 200": (result) =>
      result.status === 200,

    "CPU simulation completed within 10 seconds": (result) =>
      result.timings.duration < 10000,
  });

  applicationErrors.add(!requestSucceeded);

  sleep(0.2);
}

export function teardown() {
  console.log("HPA scaling load test completed.");
}