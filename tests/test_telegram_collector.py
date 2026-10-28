from app.telegram_collector import MessageStore

def test_upsert_and_cursor(tmp_path):
    db=MessageStore(str(tmp_path/"messages.db"))
    db.save("account1",-100123,10,"first")
    db.save("account1",-100123,10,"edited")
    assert db.conn.execute("SELECT text FROM supplier_messages").fetchone()[0]=="edited"
    db.advance("account1",-100123,10)
    db.advance("account1",-100123,9)
    assert db.cursor("account1",-100123)==10

def test_account_isolation(tmp_path):
    db=MessageStore(str(tmp_path/"messages.db"))
    db.save("a",-100123,1,"one")
    db.save("b",-100123,1,"two")
    assert db.conn.execute("SELECT count(*) FROM supplier_messages").fetchone()[0]==2
