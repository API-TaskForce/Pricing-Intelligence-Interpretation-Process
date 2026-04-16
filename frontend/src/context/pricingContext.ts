import { createContext } from "react";
import { DatasheetContextItem } from "../types";

export const PricingContext = createContext<DatasheetContextItem[] | null>(null);
