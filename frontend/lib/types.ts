export interface TestItem {
  name: string; why: string; payment: "free_gobmp" | "free_osms" | "paid_prime";
  source: string; needs_doctor_validation: boolean;
}
export interface PrimePackage {
  package_id: string; name: string; price_kzt: number | null;
  composition_note: string | null; discrepancy_note: string | null; tests: TestItem[];
}
export interface ItineraryStep { order: number; block: string; time_window: string | null; title: string; details: string; }
export interface HealthMapEntry { item: string; status: string; when: string; why: string; source: string; }
export interface ReminderPlan { channel: string; message_preview: string; due_in: string; demo: boolean; }
export interface CheckupResult {
  is_emergency: boolean; emergency_banner: string | null;
  osms_free_tests: TestItem[]; prime_package: PrimePackage | null;
  prime_addon_tests: TestItem[]; total_paid_kzt: number;
  itinerary_timeline: ItineraryStep[]; health_map: HealthMapEntry[];
  reminder: ReminderPlan | null; booking_contact_phone: string; booking_contact_email: string;
  disclaimer: string; not_diagnosis: string;
}
export interface Intake {
  age: number | null; gender: "male" | "female" | null;
  symptoms: string[]; family_history: string[]; chronic_conditions: string[];
  red_flags: string[]; is_pregnant: boolean | null; child_age_months: number | null;
  state_version: number;
}
export interface ChatResponse {
  intake: Intake; assistant_message: string; llm_status: string; result: CheckupResult | null;
}
