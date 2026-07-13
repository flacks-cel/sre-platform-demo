import http from "k6/http";
import { check, sleep } from "k6";

import { BASE_URL } from "./config.js";

export const options = {
  vus: 1,
  duration: "10s",

  thresholds: {
    http_req_failed: ["rate==0"],
    http_req_duration: ["p(95)<2000"],
  },

  tags: {
    test_type: "smoke",
    application: "jobs-api",
  },
};

export default function () {
  const response = http.get(`${BASE_URL}/health`, {
    tags: {
      endpoint: "health",
    },
  });

  check(response, {
    "health endpoint returned HTTP 200": (result) =>
      result.status === 200,
  });

  sleep(1);
}