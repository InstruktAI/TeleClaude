'use client';

import * as React from 'react';
import { Toast as RadixToast } from 'radix-ui';
import { cva, type VariantProps } from 'class-variance-authority';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

const ToastProvider = RadixToast.Provider;

const ToastViewport = React.forwardRef<
  React.ComponentRef<typeof RadixToast.Viewport>,
  React.ComponentPropsWithoutRef<typeof RadixToast.Viewport>
>(({ className, ...props }, ref) => (
  <RadixToast.Viewport
    ref={ref}
    className={cn(
      'fixed bottom-0 right-0 z-[100] flex max-h-screen w-full flex-col-reverse p-4 sm:max-w-[420px]',
      className,
    )}
    {...props}
  />
));
ToastViewport.displayName = 'ToastViewport';

const toastVariants = cva(
  'group pointer-events-auto relative flex w-full items-center justify-between gap-4 overflow-hidden rounded-md border p-4 shadow-lg transition-all data-[swipe=cancel]:translate-x-0 data-[swipe=end]:translate-x-[var(--radix-toast-swipe-end-x)] data-[swipe=move]:translate-x-[var(--radix-toast-swipe-move-x)] data-[swipe=move]:transition-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[swipe=end]:animate-out data-[state=closed]:fade-out-80 data-[state=closed]:slide-out-to-right-full data-[state=open]:slide-in-from-bottom-full',
  {
    variants: {
      variant: {
        default: 'border bg-background text-foreground',
        success:
          'border-green-500/30 bg-green-50 text-green-900 dark:bg-green-950/50 dark:text-green-100 dark:border-green-500/20',
        destructive:
          'border-destructive/30 bg-destructive/10 text-destructive dark:bg-destructive/20 dark:text-red-200',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

const Toast = React.forwardRef<
  React.ComponentRef<typeof RadixToast.Root>,
  React.ComponentPropsWithoutRef<typeof RadixToast.Root> & VariantProps<typeof toastVariants>
>(({ className, variant, ...props }, ref) => (
  <RadixToast.Root ref={ref} className={cn(toastVariants({ variant }), className)} {...props} />
));
Toast.displayName = 'Toast';

const ToastClose = React.forwardRef<
  React.ComponentRef<typeof RadixToast.Close>,
  React.ComponentPropsWithoutRef<typeof RadixToast.Close>
>(({ className, ...props }, ref) => (
  <RadixToast.Close
    ref={ref}
    className={cn(
      'absolute right-2 top-2 rounded-md p-1 opacity-0 transition-opacity hover:text-foreground focus:opacity-100 focus:outline-none group-hover:opacity-100',
      className,
    )}
    toast-close=""
    {...props}
  >
    <X className="h-4 w-4" />
  </RadixToast.Close>
));
ToastClose.displayName = 'ToastClose';

const ToastTitle = React.forwardRef<
  React.ComponentRef<typeof RadixToast.Title>,
  React.ComponentPropsWithoutRef<typeof RadixToast.Title>
>(({ className, ...props }, ref) => (
  <RadixToast.Title ref={ref} className={cn('text-sm font-semibold', className)} {...props} />
));
ToastTitle.displayName = 'ToastTitle';

const ToastDescription = React.forwardRef<
  React.ComponentRef<typeof RadixToast.Description>,
  React.ComponentPropsWithoutRef<typeof RadixToast.Description>
>(({ className, ...props }, ref) => (
  <RadixToast.Description ref={ref} className={cn('text-sm opacity-90', className)} {...props} />
));
ToastDescription.displayName = 'ToastDescription';

export type ToastVariant = VariantProps<typeof toastVariants>['variant'];

export { ToastProvider, ToastViewport, Toast, ToastClose, ToastTitle, ToastDescription };
