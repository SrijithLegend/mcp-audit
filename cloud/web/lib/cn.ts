import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** The usual class combiner. Same helper shadcn/ui generates, so its components drop in. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
