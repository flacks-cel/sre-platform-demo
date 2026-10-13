import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://jobs-api.app.svc.cluster.local:8000";
const RATE = Number(__ENV.RATE || "1");
const TIME_UNIT = __ENV.TIME_UNIT || "1s";
const DURATION = __ENV.DURATION || "2m";
const ITERATIONS = Number(__ENV.ITERATIONS || "1000000");
const PRE_ALLOCATED_VUS = Number(__ENV.PRE_ALLOCATED_VUS || "20");
const MAX_VUS = Number(__ENV.MAX_VUS || "100");

export const options = {
  noConnectionReuse: true,
  scenarios: {
    calibration: {
      executor: "constant-arrival-rate",
      rate: RATE,
      timeUnit: TIME_UNIT,
      duration: DURATION,
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
    },
  },
  thresholds: {
    http_req_failed: ["rate==0"],
    dropped_iterations: ["count==0"],
  },
  tags: {
    test_type: "praeva-spike-002-calibration",
    application: "jobs-api",
  },
};

export function setup() {
  const response = http.get(`${BASE_URL}/health`, {
    tags: { endpoint: "health-preflight" },
  });

  const ok = check(response, {
    "jobs-api is reachable before calibration": (r) => r.status === 200,
  });

  if (!ok) {
    throw new Error(
      `jobs-api unavailable at ${BASE_URL}; received HTTP ${response.status}`,
    );
  }

  console.log(
    `Spike 002 calibration: rate=${RATE}/${TIME_UNIT} duration=${DURATION} ` +
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
