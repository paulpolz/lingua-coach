import { SignIn } from "@clerk/nextjs";

import PostAuthRedirect from "@/components/PostAuthRedirect";

const POST_AUTH_URL = "/onboarding";

export default function SignInPage() {
  return (
    <div className="flex flex-1 items-center justify-center bg-background p-6">
      <PostAuthRedirect href={POST_AUTH_URL} />
      <SignIn forceRedirectUrl={POST_AUTH_URL} signUpForceRedirectUrl={POST_AUTH_URL} />
    </div>
  );
}
