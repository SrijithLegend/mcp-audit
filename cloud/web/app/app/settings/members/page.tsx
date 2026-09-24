import { redirect } from "next/navigation";

/** Members live on the organisation page; this path is kept so links do not rot. */
export default function Members() {
  redirect("/app/settings/org");
}
