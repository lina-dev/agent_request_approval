// Package api exposes the POST /decisions front door.
package api

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strings"
)

// Store persists the raw case for the worker to pick up.
type Store interface {
	Create(ctx context.Context, id string, raw []byte) error
}

// Queue enqueues a case id for asynchronous processing.
type Queue interface {
	Enqueue(ctx context.Context, id string) error
}

// Handler wires the dependencies for the decisions endpoint.
type Handler struct {
	Store Store
	Queue Queue
}

// DecideRequest is the inbound contract (spec §3).
type DecideRequest struct {
	CaseID    string `json:"case_id"`
	Documents []struct {
		URI string `json:"uri"`
	} `json:"documents"`
	Claim struct {
		Amount   float64 `json:"amount"`
		Currency string  `json:"currency"`
	} `json:"claim"`
	PolicyVersion string `json:"policy_version"`
}

const maxBody = 1 << 20 // 1 MiB cap to bound abuse

// Decide validates the request, stores it, and enqueues it (202 Accepted).
func (h *Handler) Decide(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, maxBody))
	if err != nil {
		writeErr(w, http.StatusBadRequest, "unreadable body")
		return
	}
	var req DecideRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid json")
		return
	}
	if msg := validate(&req); msg != "" {
		writeErr(w, http.StatusBadRequest, msg)
		return
	}

	ctx := r.Context()
	if err := h.Store.Create(ctx, req.CaseID, raw); err != nil {
		writeErr(w, http.StatusInternalServerError, "store error")
		return
	}
	if err := h.Queue.Enqueue(ctx, req.CaseID); err != nil {
		writeErr(w, http.StatusInternalServerError, "queue error")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted)
	_ = json.NewEncoder(w).Encode(map[string]string{"case_id": req.CaseID, "status": "accepted"})
}

// validate enforces structural + security rules; returns "" when valid.
func validate(req *DecideRequest) string {
	if req.CaseID == "" {
		return "case_id is required"
	}
	if req.PolicyVersion == "" {
		return "policy_version is required"
	}
	if req.Claim.Amount < 0 {
		return "claim.amount must be non-negative"
	}
	if len(req.Documents) > 50 {
		return "too many documents"
	}
	for _, d := range req.Documents {
		if msg := validateS3URI(d.URI); msg != "" {
			return msg
		}
	}
	return ""
}

// validateS3URI guards against bad schemes and path traversal.
func validateS3URI(uri string) string {
	if uri == "" {
		return "document uri is required"
	}
	u, err := url.Parse(uri)
	if err != nil || u.Scheme != "s3" {
		return "document uri must be s3://"
	}
	if u.Host == "" || strings.TrimPrefix(u.Path, "/") == "" {
		return "s3 uri needs bucket and key"
	}
	if strings.Contains(u.Path, "..") {
		return "s3 key path traversal rejected"
	}
	return ""
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	http.Error(w, msg, code)
}
