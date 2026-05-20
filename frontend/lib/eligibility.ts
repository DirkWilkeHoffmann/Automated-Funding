import type { BadgeProps } from "../components/ui/badge";

export type EligibilityVariant = BadgeProps["variant"];

export const eligibilityVariantMap: Record<string, EligibilityVariant> = {
  "Highly Eligible": "highly-eligible",
  Eligible: "eligible",
  "Possibly Eligible": "possibly-eligible",
  "Low Match": "low-match",
  "Not Eligible": "not-eligible",
};
