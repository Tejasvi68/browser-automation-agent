import { useState } from "react";
import { KeyRound, Plus, Trash2, Pencil, X } from "lucide-react";

const emptyForm = () => ({ label: "", domain: "", username: "", password: "", fields: [] });

export default function VaultPage({ credentials, onAddCredential, onLoadCredential, onUpdateCredential, onDeleteCredential }) {
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const reset = () => { setForm(emptyForm()); setEditingId(null); setError(""); };
  const setField = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const addField = () => setField("fields", [...form.fields, { name: "", value: "" }]);
  const updateField = (index, key, value) => setField("fields", form.fields.map((field, i) => i === index ? { ...field, [key]: value } : field));
  const removeField = (index) => setField("fields", form.fields.filter((_, i) => i !== index));

  const handleEdit = async (id) => {
    setBusy(true); setError("");
    try {
      const profile = await onLoadCredential(id);
      setEditingId(id);
      setForm({
        label: profile.label,
        domain: profile.domain,
        username: profile.username,
        password: "",
        fields: Object.entries(profile.fields || {}).map(([name, value]) => ({ name, value })),
      });
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Could not load this profile.");
    } finally { setBusy(false); }
  };

  const handleSubmit = async (event) => {
    event.preventDefault(); setBusy(true); setError("");
    const fields = Object.fromEntries(form.fields.filter((field) => field.name.trim()).map((field) => [field.name.trim(), field.value]));
    try {
      if (editingId) await onUpdateCredential(editingId, { ...form, fields });
      else await onAddCredential({ ...form, fields });
      reset();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Could not save this profile.");
    } finally { setBusy(false); }
  };

  const handleDelete = async (credential) => {
    if (!window.confirm(`Delete vault profile “${credential.label}” and its saved fields?`)) return;
    setBusy(true); setError("");
    try { await onDeleteCredential(credential.id); if (editingId === credential.id) reset(); }
    catch (err) { setError(err.response?.data?.detail || err.message || "Could not delete this profile."); }
    finally { setBusy(false); }
  };

  const inputClass = "w-full px-3 py-2 bg-black/40 border border-white/10 rounded-xl text-xs text-zinc-100 placeholder:text-zinc-500";

  return (
    <div className="p-6 max-w-6xl w-full mx-auto grid grid-cols-1 md:grid-cols-3 gap-6">
      <form onSubmit={handleSubmit} className="bg-white/[0.03] backdrop-blur-xl border border-white/[0.08] p-5 rounded-2xl space-y-3 h-fit">
        <h3 className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
          <KeyRound className="w-4 h-4 text-violet-400" /> {editingId ? "Edit Vault Profile" : "Add Vault Profile"}
        </h3>
        <input required className={inputClass} placeholder="Profile label (e.g. personal)" value={form.label} onChange={(e) => setField("label", e.target.value)} />
        <input required className={inputClass} placeholder="Website domain (e.g. example.com)" value={form.domain} onChange={(e) => setField("domain", e.target.value)} />
        <input required className={inputClass} placeholder="Username or login email" value={form.username} onChange={(e) => setField("username", e.target.value)} />
        <input type="password" required={!editingId} className={inputClass} placeholder={editingId ? "New password (leave blank to keep current)" : "Password (encrypted)"} value={form.password} onChange={(e) => setField("password", e.target.value)} />

        <div className="border-t border-white/10 pt-3 space-y-2">
          <div className="flex items-center justify-between">
            <div><div className="text-xs font-medium text-zinc-200">Reusable form fields</div><div className="text-[10px] text-zinc-500">Add details the agent may match to future forms.</div></div>
            <button type="button" onClick={addField} className="flex items-center gap-1 text-[11px] text-violet-300 hover:text-violet-200"><Plus size={14} /> Add field</button>
          </div>
          {form.fields.map((field, index) => (
            <div key={index} className="grid grid-cols-[1fr_1.2fr_auto] gap-2">
              <input className={inputClass} placeholder="Field name (e.g. phone)" value={field.name} onChange={(e) => updateField(index, "name", e.target.value)} />
              <input className={inputClass} placeholder="Value" value={field.value} onChange={(e) => updateField(index, "value", e.target.value)} />
              <button type="button" aria-label="Remove field" onClick={() => removeField(index)} className="px-2 text-zinc-500 hover:text-rose-400"><X size={15} /></button>
            </div>
          ))}
        </div>

        {error && <p className="text-xs text-rose-400">{error}</p>}
        <div className="flex gap-2">
          <button disabled={busy} type="submit" className="flex-1 py-2 rounded-xl bg-violet-600/90 hover:bg-violet-500 disabled:opacity-50 text-white text-xs font-medium">{busy ? "Saving…" : editingId ? "Update Profile" : "Encrypt & Store"}</button>
          {editingId && <button type="button" onClick={reset} className="px-3 rounded-xl border border-white/10 text-xs text-zinc-300">Cancel</button>}
        </div>
      </form>

      <div className="md:col-span-2 space-y-3">
        {credentials.map((credential) => (
          <div key={credential.id} className="bg-white/[0.03] backdrop-blur-xl border border-white/[0.08] p-4 rounded-2xl">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-medium text-zinc-100">{credential.label}</div>
                <div className="text-xs text-zinc-400 break-all">{credential.domain} · {credential.username}</div>
                <div className="flex flex-wrap gap-1.5 mt-3">
                  {(credential.fields || []).map((field) => <span key={field.id} className="text-[10px] px-2 py-1 rounded-lg bg-black/30 border border-white/10 text-zinc-300">{field.name}</span>)}
                  {(!credential.fields || credential.fields.length === 0) && <span className="text-[10px] text-zinc-500">No reusable form fields yet</span>}
                </div>
              </div>
              <div className="flex gap-1 shrink-0">
                <button type="button" disabled={busy} onClick={() => handleEdit(credential.id)} title="Edit profile" className="p-2 rounded-lg text-zinc-400 hover:text-violet-300 hover:bg-white/5"><Pencil size={15} /></button>
                <button type="button" disabled={busy} onClick={() => handleDelete(credential)} title="Delete profile" className="p-2 rounded-lg text-zinc-400 hover:text-rose-400 hover:bg-white/5"><Trash2 size={15} /></button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
