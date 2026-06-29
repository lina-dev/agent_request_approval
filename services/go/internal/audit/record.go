// Package audit builds immutable, reproducible decision records. Every record
// captures the full provenance needed to reconstruct a decision: inputs,
// citations, model versions, and the final actor (agent or human).
package audit

import (
	"context"
	"encoding/json"
)

// Decision is the terminal verdict being recorded.
type Decision struct {
	Status    string
	Citations []string
}

// CaseInput is the provenance of the case.
type CaseInput struct {
	PolicyVersion string
}

// Meta carries model/version/actor provenance.
type Meta struct {
	ModelVersions map[string]string
	FinalActor    string // "agent" | "human"
	TraceID       string
}

// Record is the immutable audit row (write-once to Object-Lock S3).
type Record struct {
	CaseID        string            `json:"case_id"`
	PolicyVersion string            `json:"policy_version"`
	Status        string            `json:"status"`
	Citations     []string          `json:"policy_citations"`
	ModelVersions map[string]string `json:"model_versions"`
	FinalActor    string            `json:"final_actor"`
	TraceID       string            `json:"trace_id"`
}

// Build assembles a deterministic audit record.
func Build(caseID string, in CaseInput, dec Decision, meta Meta) Record {
	cites := dec.Citations
	if cites == nil {
		cites = []string{}
	}
	return Record{
		CaseID:        caseID,
		PolicyVersion: in.PolicyVersion,
		Status:        dec.Status,
		Citations:     cites,
		ModelVersions: meta.ModelVersions,
		FinalActor:    meta.FinalActor,
		TraceID:       meta.TraceID,
	}
}

// Marshal serializes a record to canonical JSON.
func Marshal(r Record) ([]byte, error) {
	return json.Marshal(r)
}

// Putter writes an object (S3 Object Lock in production).
type Putter interface {
	Put(ctx context.Context, key string, body []byte) error
}

// Put writes the record under a deterministic, per-case key.
func Put(ctx context.Context, p Putter, r Record) error {
	body, err := Marshal(r)
	if err != nil {
		return err
	}
	return p.Put(ctx, "audit/"+r.CaseID+".json", body)
}
