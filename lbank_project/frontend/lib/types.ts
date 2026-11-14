export type Product = "signals" | "autotrade";
export interface ProductPlan {
  product: Product;
  label: string;
  sales_enabled: boolean;
  version: string;
  tiers: { cap_usd: number; prices_cents: Record<string, number | null> }[];
}
export interface Me {
  role: "customer" | "admin";
  username: string;
  email?: string | null;
  csrf: string;
  live_execution_supported: boolean;
}
export interface Plans {
  version: string;
  currency: string;
  tiers: { cap_usd: number; prices_cents: Record<string, number | null> }[];
  products: ProductPlan[];
}
export interface License {
  state: string;
  entries_allowed: boolean;
  signals_allowed?: boolean;
  product?: Product;
  license_id?: string;
  account_id?: string;
  cap_usd?: number;
  months?: number;
  not_before?: string;
  expires_at?: string;
  funded_capital_usd?: string;
  grace_ends_at?: string | null;
}
export interface Order {
  product: Product;
  id: string;
  cap_usd: number;
  months: number;
  kind: string;
  price_cents: number;
  status: string;
  created: number;
}
export interface BillingSnapshot {
  license: License;
  orders: Order[];
}
export interface Quote {
  product: Product;
  cap_usd: number;
  months: number;
  kind: string;
  price_cents: number;
  expires_at: string;
}
export interface Exchange {
  id: string;
  name: string;
  markets: string[];
  required_fields: Record<string, string[]>;
}
export type Cell = string | number | null | undefined;
export interface Connection {
  configured: boolean;
  exchange_id?: string;
  market?: string;
  account?: {
    status: string;
    checked_at?: number;
    snapshot?: {
      balances?: {
        asset: string;
        free: number | null;
        locked: number | null;
        total: number | null;
      }[];
      positions?: Record<string, Cell>[];
      balance_scope?: string;
      positions_complete?: boolean;
    };
  };
}
export interface Robot {
  bot: string;
  name: string;
  state: string;
  positions: Record<string, Cell>[];
  trades: Record<string, Cell>[];
}
