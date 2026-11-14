"use client";
import { useEffect } from "react";
import { captureRef } from "@/lib/referral";

/** Keeps an invite code from a shared link (?ref=CODE) until the visitor signs up. */
export default function RefCapture() {
  useEffect(() => captureRef(), []);
  return null;
}
