import { api } from "./client";
import type { Customer, Paginated } from "../types";

/**
 * DRF paginates at 20 with no page_size override configured, so a single fetch
 * would silently hide the 21st customer onwards. Walk `next` instead.
 */
export async function fetchAllCustomers(): Promise<Customer[]> {
  const all: Customer[] = [];
  let path: string | null = "/customers/";
  while (path) {
    const page: Paginated<Customer> = await api.get<Paginated<Customer>>(path);
    all.push(...page.results);
    if (page.next) {
      const url = new URL(page.next);
      path = url.pathname.replace(/^\/api/, "") + url.search;
    } else {
      path = null;
    }
  }
  return all;
}

/** Label used wherever a customer is named in a picker or a table cell. */
export function customerLabel(customer: Customer): string {
  return customer.company_name
    ? `${customer.name} (${customer.company_name})`
    : customer.name;
}
