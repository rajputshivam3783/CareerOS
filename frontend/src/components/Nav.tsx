"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, logout as apiLogout } from "@/lib/api";
import ThemeToggle from "@/components/ThemeToggle";
import NotificationBell from "@/components/NotificationBell";

export default function Nav() {
  const [on, setOn] = useState(false);
  const [role, setRole] = useState("");

  useEffect(() => {
    const yes = !!localStorage.getItem("careeros_token");
    setOn(yes);
    if (yes) {
      api("/auth/me")
        .then((u: any) => setRole(u.role))
        .catch(() => {});
    }
  }, []);

  function logout() {
    apiLogout().then(() => {
      location.href = "/";
    });
  }

  const isAdmin = on && (role === "admin" || role === "super_admin");
  const isRecruiter = on && role === "recruiter";
  const isCandidate = on && !isAdmin && !isRecruiter;

  return (
    <header>
      <a href="#main" className="skiplink">
        Skip to content
      </a>
      <div className="container nav">
        <Link href="/" className="brand">
          CareerOS
        </Link>
        <nav>
          <Link className="navlink" href="/discover">
            Discover
          </Link>
          <Link className="navlink" href="/jobs">
            Jobs
          </Link>
          <Link className="navlink" href="/government">
            Govt Portal
          </Link>
          <Link className="navlink" href="/companies">
            Companies
          </Link>

          {isCandidate && (
            <details className="navgroup">
              <summary>Workspace</summary>
              <div className="navgroup-menu">
                <Link href="/dashboard">Dashboard</Link>
                <Link href="/applications">Applications</Link>
                <Link href="/recommendations">Jobs for you</Link>
                <Link href="/job-alerts">Job alerts</Link>
                <Link href="/resume">Resume</Link>
                <Link href="/learning">Learning</Link>
                <Link href="/interview">Mock interview</Link>
                <Link href="/career-ai">Career AI</Link>
                <Link href="/career-copilot">Career Copilot</Link>
                <Link href="/subscriptions">Subscriptions</Link>
              </div>
            </details>
          )}

          {isRecruiter && (
            <Link className="navlink" href="/recruiter">
              Recruiter Dashboard
            </Link>
          )}

          {isAdmin && (
            <details className="navgroup">
              <summary>Admin</summary>
              <div className="navgroup-menu">
                <Link href="/admin">Overview</Link>
                <Link href="/admin/government">Govt admin</Link>
                <Link href="/admin/sources">Sources</Link>
                <Link href="/admin/notifications">Notification engine</Link>
                <Link href="/admin/ai">AI infrastructure</Link>
                <Link href="/admin/learning">Learning admin</Link>
              </div>
            </details>
          )}

          {on && !isRecruiter && <NotificationBell />}
          <ThemeToggle />

          {on ? (
            <button className="linkbtn" onClick={logout} style={{ marginLeft: 4 }}>
              Log out
            </button>
          ) : (
            <>
              <Link className="navlink" href="/login">
                Candidate login
              </Link>
              <Link className="navlink" href="/recruiter-login">
                Recruiter
              </Link>
              <Link className="navlink" href="/admin-login">
                Admin
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
