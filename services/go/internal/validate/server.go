package validate

import (
	"encoding/json"
	"net/http"
)

type wireInput struct {
	Claim struct {
		AmountCents int64  `json:"amount_cents"`
		Currency    string `json:"currency"`
		Date        string `json:"date"`
		Category    string `json:"category"`
	} `json:"claim"`
	Receipts []struct {
		AmountCents int64  `json:"amount_cents"`
		Date        string `json:"date"`
	} `json:"receipts"`
}

// Handler implements POST /validate. It returns {"flags": [...]}.
func Handler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var wi wireInput
	if err := json.NewDecoder(r.Body).Decode(&wi); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	in := Input{Claim: Claim{
		AmountCents: wi.Claim.AmountCents,
		Currency:    wi.Claim.Currency,
		Date:        wi.Claim.Date,
		Category:    wi.Claim.Category,
	}}
	for _, rc := range wi.Receipts {
		in.Receipts = append(in.Receipts, Receipt{AmountCents: rc.AmountCents, Date: rc.Date})
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string][]string{"flags": Validate(in)})
}
