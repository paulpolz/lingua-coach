"use client";

import { UserButton } from "@clerk/nextjs";
import { useRouter } from "next/navigation";

function MenuIcon({ path }: { path: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
      <path fillRule="evenodd" d={path} clipRule="evenodd" />
    </svg>
  );
}

export default function AccountMenu() {
  const router = useRouter();

  return (
    <UserButton>
      <UserButton.MenuItems>
        <UserButton.Action
          label="Progress"
          labelIcon={
            <MenuIcon path="M3 4.25A2.25 2.25 0 015.25 2h9.5A2.25 2.25 0 0117 4.25v11.5A2.25 2.25 0 0114.75 18h-9.5A2.25 2.25 0 013 15.75V4.25zM6 6.5a.75.75 0 000 1.5h8a.75.75 0 000-1.5H6zM6 10a.75.75 0 000 1.5h5a.75.75 0 000-1.5H6z" />
          }
          onClick={() => router.push("/reports/progress")}
        />
        <UserButton.Action
          label="Error Log"
          labelIcon={
            <MenuIcon path="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l6.518 11.59c.75 1.334-.213 2.986-1.742 2.986H3.481c-1.53 0-2.493-1.652-1.743-2.986L8.257 3.1zM11 13a1 1 0 10-2 0 1 1 0 002 0zm-.75-6.75a.75.75 0 00-1.5 0v4a.75.75 0 001.5 0v-4z" />
          }
          onClick={() => router.push("/reports/errors")}
        />
        <UserButton.Action
          label="Roadmap"
          labelIcon={
            <MenuIcon path="M8.5 3.75a.75.75 0 00-1.5 0v1.5H5.25a.75.75 0 000 1.5H7v1.5H5.25a.75.75 0 000 1.5H7v1.5H5.25a.75.75 0 000 1.5H7v1.5a.75.75 0 001.5 0v-1.5h1.75a.75.75 0 000-1.5H8.5v-1.5h6.25a.75.75 0 000-1.5H8.5v-1.5h1.75a.75.75 0 000-1.5H8.5v-1.5z" />
          }
          onClick={() => router.push("/reports/roadmap")}
        />
        <UserButton.Action
          label="4-Week Plan"
          labelIcon={
            <MenuIcon path="M6.75 2.25A.75.75 0 016 3v.75H4.75A1.75 1.75 0 003 5.5v10.75c0 .966.784 1.75 1.75 1.75h10.5A1.75 1.75 0 0017 16.25V5.5a1.75 1.75 0 00-1.75-1.75H14V3a.75.75 0 00-1.5 0v.75h-5V3a.75.75 0 00-.75-.75zM4.5 8h11v8.25a.25.25 0 01-.25.25H4.75a.25.25 0 01-.25-.25V8z" />
          }
          onClick={() => router.push("/reports/four-week-plan")}
        />
      </UserButton.MenuItems>
    </UserButton>
  );
}