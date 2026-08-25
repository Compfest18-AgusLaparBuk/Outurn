"use client";

import {
  CheckCircleIcon as CheckCircle,
  FileTextIcon as FileText,
  MapPinIcon as MapPin,
  ShieldCheckIcon as ShieldCheck,
  SidebarSimpleIcon as SidebarSimple,
  UploadSimpleIcon as UploadSimple,
} from "@phosphor-icons/react";
import { useState } from "react";
import {
  Sidebar,
  SidebarProvider,
} from "@cloudflare/kumo/components/sidebar";

const workflow = [
  ["stage-intake", "Shipment intake", FileText],
  ["stage-documents", "Document collection", UploadSimple],
  ["stage-evidence", "AI evidence", FileText],
  ["stage-reconciliation", "Reconciliation", CheckCircle],
  ["stage-destination", "Destination check", MapPin],
  ["stage-risk", "Risk assessment", ShieldCheck],
  ["stage-resolution", "Resolution and re-check", UploadSimple],
  ["stage-final-decision", "Dispatch decision", CheckCircle],
] as const;

export function ShipmentAssuranceShell({
  children,
  currentStage,
}: {
  children: React.ReactNode;
  currentStage: number;
}) {
  const [open, setOpen] = useState(true);

  return (
    <div className="shipment-shell">
      <SidebarProvider
        open={open}
        onOpenChange={setOpen}
        collapsible="icon"
        mobileBreakpoint={860}
        className="shipment-shell__layout"
      >
        <Sidebar className="shipment-sidebar">
          <Sidebar.Header className="shipment-sidebar__header">
            <div className="shipment-brand">
              <span className="shipment-brand__mark" aria-hidden="true">O</span>
              <span className="shipment-brand__copy">
                <strong>Outurn</strong>
                <span>Shipment assurance</span>
              </span>
            </div>
            <Sidebar.Trigger aria-label="Toggle workflow navigation">
              <SidebarSimple size={16} aria-hidden="true" />
            </Sidebar.Trigger>
          </Sidebar.Header>
          <Sidebar.Content aria-label="Shipment assurance workflow">
            <Sidebar.Group>
              <Sidebar.GroupLabel>Current shipment</Sidebar.GroupLabel>
              <Sidebar.Menu>
                {workflow.map(([id, label, Icon], index) => {
                  const active = index === currentStage;
                  const complete = index < currentStage;
                  return (
                    <Sidebar.MenuButton
                      key={id}
                      href={`#${id}`}
                      icon={Icon}
                      active={active}
                      tooltip={label}
                      aria-current={active ? "step" : undefined}
                    >
                      <span>{label}</span>
                      {complete && <CheckCircle size={14} weight="fill" aria-label="Complete" />}
                    </Sidebar.MenuButton>
                  );
                })}
              </Sidebar.Menu>
            </Sidebar.Group>
          </Sidebar.Content>
          <Sidebar.Footer className="shipment-sidebar__footer">
            <span className="shipment-sidebar__note">AI explains the evidence. Rules decide dispatch.</span>
          </Sidebar.Footer>
        </Sidebar>
        <div className="shipment-main">
          <header className="shipment-topbar">
            <div>
              <span className="shipment-topbar__eyebrow">Pre-dispatch control</span>
              <strong>One shipment, one assurance trail</strong>
            </div>
            <span className="shipment-topbar__status">Synchronous check</span>
          </header>
          {children}
        </div>
      </SidebarProvider>
    </div>
  );
}
