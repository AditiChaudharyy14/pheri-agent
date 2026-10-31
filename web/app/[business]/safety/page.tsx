import { redirect } from "next/navigation";

// Safety moved into the Night shift: what came in overnight, how it was read, and who reads it.
export default async function SafetyPage({ params }: PageProps<"/[business]/safety">) {
  const { business } = await params;
  redirect(`/${business}/night`);
}
