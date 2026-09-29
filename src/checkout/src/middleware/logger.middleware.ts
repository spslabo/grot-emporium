/**
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: MIT-0
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this
 * software and associated documentation files (the "Software"), to deal in the Software
 * without restriction, including without limitation the rights to use, copy, modify,
 * merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
 * permit persons to whom the Software is furnished to do so.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
 * INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
 * PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
 * OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
 * SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */

import { Injectable, Logger, NestMiddleware } from '@nestjs/common';
import { Request, Response, NextFunction } from 'express';
import { context, trace } from '@opentelemetry/api';
import { InjectMetric } from '@willsoto/nestjs-prometheus';
import { Histogram } from 'prom-client';

@Injectable()
export class LoggerMiddleware implements NestMiddleware {
  private logger = new Logger(`HTTP`);
  constructor(@InjectMetric('http_server_request_duration_seconds') private readonly duration: Histogram<string>) {}
  use(request: Request, response: Response, next: NextFunction) {
    const startAt = process.hrtime();
    const { method } = request;
    const spanContext = trace.getSpan(context.active())?.spanContext();

    response.on('finish', () => {
      const { statusCode } = response;
      const diff = process.hrtime(startAt);
      const responseTime = diff[0] * 1e3 + diff[1] * 1e-6;
      const route = request.route?.path || 'unmatched';
      if (route !== '/metrics') {
        this.duration.observe({ method, route, status: String(statusCode) }, responseTime / 1000);
      }
      this.logger.log({
        event: 'http_request',
        service_name: process.env.OTEL_SERVICE_NAME || 'grot-checkout',
        service_namespace: 'grot-emporium',
        method,
        route,
        status: statusCode,
        duration_ms: responseTime,
        trace_id: spanContext?.traceId,
        span_id: spanContext?.spanId,
      });
    });

    next();
  }
}
