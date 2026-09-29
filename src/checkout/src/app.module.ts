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

import { MiddlewareConsumer, Module, NestModule } from '@nestjs/common';
import configuration from './config/configuration';
import { AppController } from './app.controller';
import { ConfigModule } from '@nestjs/config';
import { TerminusModule } from '@nestjs/terminus';
import { CheckoutModule } from './checkout/checkout.module';
import { LoggerMiddleware } from './middleware/logger.middleware';
import { PrometheusModule, makeHistogramProvider } from '@willsoto/nestjs-prometheus';
import { OpenTelemetryModule } from 'nestjs-otel';
import { ChaosController } from './chaos/chaos.controller';
import { ChaosService } from './chaos/chaos.service';
import { ChaosHealthIndicator } from './chaos/chaos.health';
import { ChaosMiddleware } from './chaos/chaos.middleware';
import { TelemetryLifecycle } from './telemetry.lifecycle';

const OpenTelemetryModuleConfig = OpenTelemetryModule.forRoot({});

@Module({
  imports: [
    ConfigModule.forRoot({
      load: [configuration],
    }),
    TerminusModule,
    PrometheusModule.register(),
    CheckoutModule,
    OpenTelemetryModuleConfig,
  ],
  controllers: [AppController, ChaosController],
  providers: [ChaosService, ChaosHealthIndicator, TelemetryLifecycle,
    makeHistogramProvider({
      name: 'http_server_request_duration_seconds',
      help: 'Checkout HTTP duration by bounded route, method, and status.',
      labelNames: ['method', 'route', 'status'],
      buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
    }),
  ],
})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer) {
    consumer.apply(LoggerMiddleware).exclude('health').forRoutes('*');
    consumer.apply(ChaosMiddleware).forRoutes('checkout/*splat');
  }
}
