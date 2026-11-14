// Pay an invoice from a browser wallet (Trust Wallet's extension or in-app browser, or any EIP-1193 wallet) on
// BNB Smart Chain. The wallet shows the exact token, amount and address for the customer to approve; the site
// never sees keys and confirms the payment from the chain, not from this call.

type Ethereum = {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
  isTrust?: boolean;
  isTrustWallet?: boolean;
};

export function injectedWallet(): Ethereum | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    ethereum?: Ethereum;
    trustwallet?: Ethereum;
  };
  return w.trustwallet ?? w.ethereum ?? null;
}

export function isTrustWallet(wallet: Ethereum | null) {
  return !!wallet && !!(wallet.isTrust || wallet.isTrustWallet);
}

const BSC = {
  chainId: "0x38",
  chainName: "BNB Smart Chain",
  nativeCurrency: { name: "BNB", symbol: "BNB", decimals: 18 },
  rpcUrls: ["https://bsc-rpc.publicnode.com"],
  blockExplorerUrls: ["https://bscscan.com"],
};

const word = (hex: string) =>
  hex.replace(/^0x/, "").toLowerCase().padStart(64, "0");

/** ERC-20 transfer(address,uint256) call data. */
export function transferData(
  to: string,
  amountMicro: number,
  decimals: number,
) {
  const units = BigInt(amountMicro) * 10n ** BigInt(decimals - 6);
  return "0xa9059cbb" + word(to) + word(units.toString(16));
}

export async function payWithWallet(invoice: {
  address: string;
  contract: string;
  amount_micro: number;
  decimals: number;
}) {
  const wallet = injectedWallet();
  if (!wallet) throw Error("no-wallet");
  const [from] = (await wallet.request({
    method: "eth_requestAccounts",
  })) as string[];
  try {
    await wallet.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: BSC.chainId }],
    });
  } catch (error) {
    if ((error as { code?: number }).code !== 4902) throw error;
    await wallet.request({ method: "wallet_addEthereumChain", params: [BSC] });
  }
  return (await wallet.request({
    method: "eth_sendTransaction",
    params: [
      {
        from,
        to: invoice.contract,
        value: "0x0",
        data: transferData(
          invoice.address,
          invoice.amount_micro,
          invoice.decimals,
        ),
      },
    ],
  })) as string;
}
