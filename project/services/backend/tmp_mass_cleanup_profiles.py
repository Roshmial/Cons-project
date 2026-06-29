import json
import app

updated = []
with app.db_connect() as conn:
    rows = conn.execute("SELECT * FROM users WHERE deleted_at IS NULL ORDER BY id").fetchall()
    for row in rows:
        profile = app.assistant_profile_from_row(row, conn)
        memory = app.normalize_memory_items(app.json_loads(row["interaction_memory_json"], []))
        old_profile_text = row["assistant_profile_json"] or "{}"
        old_memory_text = row["interaction_memory_json"] or "[]"
        new_profile_text = json.dumps(profile, ensure_ascii=False)
        new_memory_text = json.dumps(memory, ensure_ascii=False)
        if new_profile_text != old_profile_text or new_memory_text != old_memory_text:
            conn.execute(
                "UPDATE users SET assistant_profile_json = ?, interaction_memory_json = ?, updated_at = ? WHERE id = ?",
                (new_profile_text, new_memory_text, app.now_iso(), row["id"]),
            )
            updated.append({
                "id": int(row["id"]),
                "email": row["email"],
                "old_memory_len": len(old_memory_text),
                "new_memory_len": len(new_memory_text),
                "new_profile": profile,
                "new_memory": memory,
            })
print(json.dumps(updated, ensure_ascii=False))
