import type { Chat } from "./chat";

const databaseName = "laris-web";
const storeName = "chats";
let database: Promise<IDBDatabase> | undefined;

function openHistory() {
  return database ??= new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(databaseName, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(storeName, { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      database = undefined;
      reject(request.error);
    };
  });
}

export async function readHistory(): Promise<Chat[]> {
  const db = await openHistory();
  return new Promise((resolve, reject) => {
    const request = db.transaction(storeName).objectStore(storeName).getAll();
    request.onsuccess = () => resolve(request.result.sort((a: Chat, b: Chat) => b.updatedAt - a.updatedAt));
    request.onerror = () => reject(request.error);
  });
}

export async function writeHistory(chat: Chat | string) {
  const db = await openHistory();
  return new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(storeName, "readwrite");
    const store = transaction.objectStore(storeName);
    if (typeof chat === "string") store.delete(chat);
    else store.put(chat);
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(transaction.error);
  });
}
