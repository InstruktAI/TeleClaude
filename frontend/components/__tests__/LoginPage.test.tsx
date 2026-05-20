// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import LoginPage from '@/app/(auth)/login/page';

const searchParamsMock = vi.fn();

vi.mock('next/navigation', () => ({
  useSearchParams: () => searchParamsMock(),
}));

describe('LoginPage', () => {
  const originalLocation = window.location;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    searchParamsMock.mockReturnValue({
      get: () => null,
    });
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        ...originalLocation,
        origin: 'http://localhost:3000',
        href: 'http://localhost:3000/login',
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
    });
  });

  it('renders a plain email input instead of a people picker', () => {
    render(<LoginPage />);

    expect(screen.getByLabelText('Email address').getAttribute('type')).toBe('email');
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('requests an OTP for the entered email and advances to verification', async () => {
    fetchMock
      .mockResolvedValueOnce({
        json: async () => ({ csrfToken: 'csrf-token' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        type: 'basic',
        status: 200,
      });

    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText('Email address'), {
      target: { value: 'tester@instrukt.ai' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send verification code' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/auth/csrf');
      expect(fetchMock).toHaveBeenNthCalledWith(
        2,
        '/api/auth/signin/nodemailer',
        expect.objectContaining({
          method: 'POST',
          redirect: 'manual',
        }),
      );
    });

    const signInCall = fetchMock.mock.calls[1];
    const body = signInCall?.[1]?.body;
    expect(body).toBeInstanceOf(URLSearchParams);
    expect((body as URLSearchParams).get('email')).toBe('tester@instrukt.ai');

    expect(await screen.findByText(/Enter the 6-digit code sent to/i)).toBeDefined();
    expect(screen.getByText('tester@instrukt.ai')).toBeDefined();
  });
});
