import { useContext } from "react";
import { PricingContext } from "../context/pricingContext";

export function usePricingContext() {
  const pricingContext = useContext(PricingContext);
  if (!pricingContext) {
    throw new Error("usePricingContext must be used within PricingContext.Provider");
  }
  return pricingContext;
}
