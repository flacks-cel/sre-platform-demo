import http from "k6/http";
import { check } from "k6";

const BASE_URL = "http://jobs-api.app.svc.cluster.local:8000";
const ITERATIONS = 1000000;

export const options = {
  noConnectionReuse: true,
  scenarios: {
    evidential: {
      executor: "constant-arrival-rate",
      rate: 3,
      timeUnit: "4s",
      duration: "8m",
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
  },
  thresholds: {
    http_req_failed: ["rate==0"],
    dropped_iterations: ["count==0"],
  },
  tags: {
    test_type: "praeva-spike-002-evidential",
    application: "jobs-api",
  },
};

export function setup() {
  const response = http.get(`${BASE_URL}/health`, {
    tags: { endpoint: "health-preflight" },
  });

  const ok = check(response, {
    "jobs-api is reachable before evidential load": (r) => r.status === 200,
  });

  if (!ok) {
    throw new Error(
      `jobs-api unavailable at ${BASE_URL}; received HTTP ${response.status}`,
    );
  }

  console.log(
    `Spike 002 evidential load: rate=3/4s duration=8m ` +
      `iterations=${ITERATIONS} target=${BASE_URL}`,
  );
}

export default function () {
  const response = http.get(
    `${BASE_URL}/simulate/cpu-work?iterations=${ITERATIONS}`,
    {
      timeout: "30s",
      tags: { endpoint: "cpu-work" },
    },
  );

  check(response, {
    "cpu-work returned HTTP 200": (r) => r.status === 200,
  });
}
