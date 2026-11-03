import 'reflect-metadata';
import { HttpOrdersService } from './HttpOrdersService';
import { CheckoutService } from '../checkout.service';
import { InMemoryCheckoutRepository } from '../repositories/InMemoryCheckoutRepository';
import { MockShippingService } from '../shipping/MockShippingService';
import { CheckoutRequest } from '../models/CheckoutRequest';

const productId = 'cc789f85-1476-452a-8100-9e74502198e0';

// Exercise the real serializer and HTTP boundary, not just createOrder's input.
describe('checkout to Orders contract', () => {
  afterEach(() => jest.restoreAllMocks());

  it('preserves UUID product identity and unit price through storage and submission', async () => {
    const fetchMock = jest
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify({ id: 'order-123' }), { status: 200 }),
      );
    const service = new CheckoutService(
      new InMemoryCheckoutRepository(),
      new HttpOrdersService('http://orders.test'),
      new MockShippingService('test'),
    );
    const request: CheckoutRequest = {
      items: [
        { id: productId, name: 'Original Grot', quantity: 2, price: 15 },
        {
          id: '87e89b11-d319-446d-b9be-50adcca5224a',
          name: 'On-Call Grot',
          quantity: 1,
          price: 20,
        },
      ],
      shippingAddress: {
        firstName: 'Demo',
        lastName: 'Probe',
        email: 'probe@example.test',
        address1: '1 Example Street',
        address2: '',
        city: 'Demo',
        state: 'CA',
        zip: '90210',
      },
      deliveryOptionToken: 'standard',
    };
    await service.update('customer', request);
    expect((await service.get('customer')).items[0].id).toBe(productId);
    const submitted = await service.submit('customer');
    expect(submitted.orderId).toBe('order-123');
    const [url, options] = fetchMock.mock.calls[0];
    expect(url.toString()).toBe('http://orders.test/orders');
    const body = JSON.parse(options.body as string);
    expect(body.items).toEqual([
      { productId, unitCost: 15, quantity: 2, totalCost: 30 },
      {
        productId: request.items[1].id,
        unitCost: 20,
        quantity: 1,
        totalCost: 20,
      },
    ]);
    expect(body.shippingAddress.email).toBe('probe@example.test');
    expect(await service.get('customer')).toBeNull();
  });
});
