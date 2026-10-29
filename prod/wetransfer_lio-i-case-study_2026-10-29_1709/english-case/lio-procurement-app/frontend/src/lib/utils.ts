import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merge Tailwind CSS classes with clsx
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format currency value
 */
export function formatCurrency(value: number, currency: string = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
  }).format(value);
}

/**
 * Format date
 */
export function formatDate(date: string | Date): string {
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  }).format(new Date(date));
}

/**
 * Format date and time
 */
export function formatDateTime(date: string | Date): string {
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(date));
}

/**
 * Get status badge color
 */
export function getStatusColor(status: 'open' | 'in_progress' | 'closed'): string {
  const colors = {
    open: 'bg-green-100 text-green-800',
    in_progress: 'bg-amber-100 text-amber-800',
    closed: 'bg-ink-800/[0.06] text-ink/70',
  };
  return colors[status] || colors.open;
}

/**
 * Get status label
 */
export function getStatusLabel(status: 'open' | 'in_progress' | 'closed'): string {
  const labels = {
    open: 'Open',
    in_progress: 'In Progress',
    closed: 'Closed',
  };
  return labels[status] || status;
}


/**
 * Approval badge text: "Auto-approved" when the organization's limit approved the request.
 */
export function approvalLabel(request: {
  approval_status: string;
  approval_method?: string | null;
}): string {
  if (request.approval_status === 'approved' && request.approval_method === 'auto') {
    return 'Auto-approved';
  }
  return request.approval_status.charAt(0).toUpperCase() + request.approval_status.slice(1);
}
