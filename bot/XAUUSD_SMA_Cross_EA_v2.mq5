//+------------------------------------------------------------------+
//| XAUUSD_SMA_Cross_EA_v2.mq5                                       |
//| SMA100 / SMA5000 cross on 1-minute candles (docs/sma-cross-spec) |
//| + reports to the Bot Console server and obeys its commands       |
//|                                                                  |
//| Needs: Tools > Options > Expert Advisors > Allow WebRequest for  |
//| the ServerUrl below. The bot never receives a broker password.   |
//+------------------------------------------------------------------+
#property copyright "Bot Console"
#property version   "0.60"
#property strict

#include <Trade\Trade.mqh>

input string ServerUrl        = "http://127.0.0.1:8000"; // Bot Console server
input string BotKey           = "";                      // from server/config.json
input long   InpMagic         = 550011;                  // magic number of this strategy
input int    InpReportSeconds = 5;                       // report interval
input int    InpHistoryBars   = 6000;                    // 1-minute candles sent on first connect

#define BOT_VERSION "0.6.0"
#define PIP         0.10     // 1 pip = 0.10 price units on gold

CTrade   trade;
int      hFast = INVALID_HANDLE, hSlow = INVALID_HANDLE;
datetime lastBarTime = 0;

// ---- settings (changed only by commands from the dashboard, saved to a file)
double nextLot = 0.01, maxLot = 0.10;
int    tpPips = 300, slPips = 100, hoursStart = 210, hoursEnd = 660, nearPips = 0, settingsRev = 0;
bool   useHours = true, enabled = true, paused = false;

// ---- reporting
ulong    seq = 0;
string   bootId = "";
string   closedThrough = "", barsThrough = "";
string   sigQ[];            // signals not yet reported
string   resQ[];            // command results not yet acknowledged
string   resIds[];
string   handled[];         // command ids already handled (kept across restarts)
uint     nextReportTick = 0;
int      backoffS = 5;

// ---- trading state
int      lastCrossSide = 0;         // +1 last cross was up, -1 down
int      pendEntrySide = 0;         // an entry waiting to be placed (retried for 5 minutes)
datetime pendEntryUntil = 0;
datetime pendEntryCandle = 0;
bool     pendWarned = false, closeWarned = false, nearFlag = false;
uint     lastRetry = 0;
int      sigCounter = 0;
string   lastError = "";

// ---- manual close jobs (retried until the command expires)
string   mcCmd[]; ulong mcTicket[]; string mcExpires[];

const string STATE_FILE = "sma_bot_state.txt";

//+------------------------------------------------------------------+
//| helpers                                                          |
//+------------------------------------------------------------------+
long GmtOffset() { long o = (long)(TimeTradeServer() - TimeGMT()); return ((o + 900) / 1800) * 1800; }
string Iso(datetime t) { MqlDateTime m; TimeToStruct(t, m); return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ", m.year, m.mon, m.day, m.hour, m.min, m.sec); }
string IsoSrv(datetime serverTime) { return Iso(serverTime - (datetime)GmtOffset()); }
string NowIso() { return Iso(TimeGMT()); }
string D(double v, int digits) { return DoubleToString(v, digits); }
string JEsc(string s) { StringReplace(s, "\\", "\\\\"); StringReplace(s, "\"", "'"); return s; }
string OrNull(double v, int digits) { return v > 0 ? D(v, digits) : "null"; }
string Side(long ptype) { return ptype == POSITION_TYPE_BUY ? "buy" : "sell"; }
double NormLot(double lot)
{
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   lot = MathFloor(lot / step + 1e-9) * step;
   return MathMax(mn, MathMin(mx, NormalizeDouble(lot, 2)));
}
bool InSession()
{
   if(!useHours) return true;
   MqlDateTime t; TimeToStruct(TimeGMT() + 19800, t);
   int now = t.hour * 60 + t.min;
   if(hoursStart < hoursEnd) return (now >= hoursStart && now < hoursEnd);
   return (now >= hoursStart || now < hoursEnd);
}
bool IsHandled(string id) { for(int i = 0; i < ArraySize(handled); i++) if(handled[i] == id) return true; return false; }

//--- tiny JSON reader: enough for the server's reply (keys we know, no escapes in values)
string JRaw(const string &src, string key, int from = 0)
{
   int p = StringFind(src, "\"" + key + "\"", from);
   if(p < 0) return "";
   p = StringFind(src, ":", p);
   if(p < 0) return "";
   p++;
   while(p < StringLen(src) && (StringGetCharacter(src, p) == ' ' || StringGetCharacter(src, p) == '\n')) p++;
   if(StringGetCharacter(src, p) == '"')
   {
      int e = StringFind(src, "\"", p + 1);
      return e < 0 ? "" : StringSubstr(src, p + 1, e - p - 1);
   }
   int e = p;
   while(e < StringLen(src) && StringGetCharacter(src, e) != ',' && StringGetCharacter(src, e) != '}' && StringGetCharacter(src, e) != ']') e++;
   string v = StringSubstr(src, p, e - p);
   StringTrimLeft(v); StringTrimRight(v);
   return v == "null" ? "" : v;
}
bool JHas(const string &src, string key) { return StringFind(src, "\"" + key + "\"") >= 0; }
string JBlock(const string &src, string key, ushort open, ushort close)   // the {...} or [...] after "key":
{
   int p = StringFind(src, "\"" + key + "\"");
   if(p < 0) return "";
   p = StringFind(src, CharToString(open), p);
   if(p < 0) return "";
   int depth = 0;
   for(int i = p; i < StringLen(src); i++)
   {
      ushort c = StringGetCharacter(src, i);
      if(c == open) depth++;
      else if(c == close) { depth--; if(depth == 0) return StringSubstr(src, p, i - p + 1); }
   }
   return "";
}

//+------------------------------------------------------------------+
//| saved state                                                      |
//+------------------------------------------------------------------+
void SaveState()
{
   int h = FileOpen(STATE_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE) return;
   FileWriteString(h, "nextLot=" + D(nextLot, 2) + "\n" + "maxLot=" + D(maxLot, 2) + "\n" + "tpPips=" + IntegerToString(tpPips) + "\n" + "slPips=" + IntegerToString(slPips) + "\n");
   FileWriteString(h, "useHours=" + (useHours ? "1" : "0") + "\n" + "hoursStart=" + IntegerToString(hoursStart) + "\n" + "hoursEnd=" + IntegerToString(hoursEnd) + "\n");
   FileWriteString(h, "nearPips=" + IntegerToString(nearPips) + "\n" + "settingsRev=" + IntegerToString(settingsRev) + "\n" + "enabled=" + (enabled ? "1" : "0") + "\n" + "paused=" + (paused ? "1" : "0") + "\n");
   int from = MathMax(0, ArraySize(handled) - 200);
   for(int i = from; i < ArraySize(handled); i++) FileWriteString(h, "h=" + handled[i] + "\n");
   FileClose(h);
}
void LoadState()
{
   int h = FileOpen(STATE_FILE, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE) return;
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      int eq = StringFind(line, "=");
      if(eq < 0) continue;
      string k = StringSubstr(line, 0, eq), v = StringSubstr(line, eq + 1);
      if(k == "nextLot") nextLot = StringToDouble(v);
      else if(k == "maxLot") maxLot = StringToDouble(v);
      else if(k == "tpPips") tpPips = (int)StringToInteger(v);
      else if(k == "slPips") slPips = (int)StringToInteger(v);
      else if(k == "useHours") useHours = (v == "1");
      else if(k == "hoursStart") hoursStart = (int)StringToInteger(v);
      else if(k == "hoursEnd") hoursEnd = (int)StringToInteger(v);
      else if(k == "nearPips") nearPips = (int)StringToInteger(v);
      else if(k == "settingsRev") settingsRev = (int)StringToInteger(v);
      else if(k == "enabled") enabled = (v == "1");
      else if(k == "paused") paused = (v == "1");
      else if(k == "h") { int n = ArraySize(handled); ArrayResize(handled, n + 1); handled[n] = v; }
   }
   FileClose(h);
}

//+------------------------------------------------------------------+
//| signals and command results (queued for the next report)         |
//+------------------------------------------------------------------+
void AddSignal(string kind, int side, bool acted, double lot, string reason, datetime candleSrv)
{
   string sideTxt = side > 0 ? "\"buy\"" : side < 0 ? "\"sell\"" : "null";
   string cc = IsoSrv(candleSrv > 0 ? candleSrv : TimeTradeServer());
   StringSetCharacter(cc, 17, '0'); StringSetCharacter(cc, 18, '0');      // candle_close is on a whole minute
   sigCounter++;
   string id = "sig-" + StringSubstr(bootId, 0, 6) + "-" + IntegerToString(sigCounter);
   string j = "{\"signal_id\":\"" + id + "\",\"strategy_id\":\"sma_cross\",\"time\":\"" + NowIso() + "\",\"candle_close\":\"" + cc + "\",\"symbol\":\"" + _Symbol + "\",\"kind\":\"" + kind + "\",\"side\":" + sideTxt +
              ",\"acted\":" + (acted ? "true" : "false") + ",\"lot\":" + (lot > 0 ? D(lot, 2) : "null") + ",\"reason\":\"" + JEsc(reason) + "\"}";
   int n = ArraySize(sigQ);
   if(n > 200) return;
   ArrayResize(sigQ, n + 1); sigQ[n] = j;
}
void AddResult(string id, string status, string reason)
{
   int n = ArraySize(resQ);
   ArrayResize(resQ, n + 1); ArrayResize(resIds, n + 1);
   resIds[n] = id;
   resQ[n] = "{\"command_id\":\"" + id + "\",\"status\":\"" + status + "\",\"reason\":" + (reason == "" ? "null" : "\"" + JEsc(reason) + "\"") + ",\"at\":\"" + NowIso() + "\"}";
}
void MarkHandled(string id) { int n = ArraySize(handled); ArrayResize(handled, n + 1); handled[n] = id; SaveState(); }

//+------------------------------------------------------------------+
//| positions                                                        |
//+------------------------------------------------------------------+
bool IsOwn(const string sym, long magic) { return magic == InpMagic && sym == _Symbol; }
int OwnCount()
{
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(IsOwn(PositionGetString(POSITION_SYMBOL), PositionGetInteger(POSITION_MAGIC))) c++;
   }
   return c;
}
// Close own positions of one direction. Returns true when none is left open.
bool CloseOwn(long ptype, string why)
{
   bool allClosed = true;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(!IsOwn(PositionGetString(POSITION_SYMBOL), PositionGetInteger(POSITION_MAGIC))) continue;
      if(PositionGetInteger(POSITION_TYPE) != ptype) continue;
      if(trade.PositionClose(t) && (trade.ResultRetcode() == TRADE_RETCODE_DONE))
      {
         AddSignal("exit", 0, true, 0, why, TimeTradeServer());
         closeWarned = false;
      }
      else
      {
         allClosed = false;
         if(!closeWarned)
         {
            closeWarned = true;
            AddSignal("skipped", ptype == POSITION_TYPE_BUY ? -1 : 1, false, 0, "Broker refused the close: " + trade.ResultRetcodeDescription() + ". Retrying every 10 seconds.", TimeTradeServer());
         }
      }
   }
   return allClosed;
}

//+------------------------------------------------------------------+
//| the strategy (docs/sma-cross-spec.md)                            |
//+------------------------------------------------------------------+
void TryEntry()
{
   if(pendEntrySide == 0) return;
   int side = pendEntrySide;
   if(TimeCurrent() > pendEntryUntil)
   {
      AddSignal("skipped", side, false, 0, "Missed: market closed for more than 5 minutes.", pendEntryCandle);
      pendEntrySide = 0; pendWarned = false; return;
   }
   if(!enabled || paused) { AddSignal("skipped", side, false, 0, "Auto was switched off before the order was sent.", pendEntryCandle); pendEntrySide = 0; return; }
   if(OwnCount() > 0) return;                                   // wait until the opposite trade has closed
   double lot = NormLot(nextLot);
   if(lot > maxLot + 1e-9) { AddSignal("skipped", side, false, 0, "Lot " + D(lot, 2) + " is above the largest lot allowed (" + D(maxLot, 2) + ").", pendEntryCandle); pendEntrySide = 0; return; }
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int dg = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   bool ok;
   if(side > 0) ok = trade.Buy(lot, _Symbol, 0, NormalizeDouble(ask - slPips * PIP, dg), NormalizeDouble(ask + tpPips * PIP, dg), "SMA cross BUY");
   else         ok = trade.Sell(lot, _Symbol, 0, NormalizeDouble(bid + slPips * PIP, dg), NormalizeDouble(bid - tpPips * PIP, dg), "SMA cross SELL");
   if(ok && (trade.ResultRetcode() == TRADE_RETCODE_DONE || trade.ResultRetcode() == TRADE_RETCODE_PLACED))
   {
      for(int i = PositionsTotal() - 1; i >= 0; i--)           // remember the stop the order opened with
      {
         ulong t = PositionGetTicket(i);
         if(t == 0 || !IsOwn(PositionGetString(POSITION_SYMBOL), PositionGetInteger(POSITION_MAGIC))) continue;
         GlobalVariableSet("slo_" + (string)PositionGetInteger(POSITION_IDENTIFIER), PositionGetDouble(POSITION_SL));
      }
      MqlDateTime m; TimeToStruct(TimeGMT(), m);
      string word = side > 0 ? "above" : "below";
      AddSignal("entry", side, true, lot, "SMA 100 crossed " + word + " SMA 5000 on the " + StringFormat("%02d:%02d", m.hour, m.min) + " candle.", pendEntryCandle);
      pendEntrySide = 0; pendWarned = false;
   }
   else if(!pendWarned)
   {
      pendWarned = true;
      AddSignal("skipped", side, false, 0, "Broker refused the order: " + trade.ResultRetcodeDescription() + ". Retrying for up to 5 minutes.", pendEntryCandle);
   }
}

// Every 10 seconds: any own trade against the last cross is closed, and a waiting entry is retried.
void EnforceCross()
{
   if(lastCrossSide == 0) return;
   CloseOwn(lastCrossSide > 0 ? POSITION_TYPE_SELL : POSITION_TYPE_BUY,
            lastCrossSide > 0 ? "Closed: SMA 100 crossed back above SMA 5000." : "Closed: SMA 100 crossed back below SMA 5000.");
   TryEntry();
}

void CheckNewBar()
{
   datetime bt = iTime(_Symbol, PERIOD_M1, 0);
   if(bt == 0 || bt == lastBarTime) return;
   lastBarTime = bt;
   double f[2], s[2];
   if(CopyBuffer(hFast, 0, 1, 2, f) != 2 || CopyBuffer(hSlow, 0, 1, 2, s) != 2) return;   // needs 5000+ candles of history
   bool up = (f[0] <= s[0] && f[1] > s[1]);
   bool dn = (f[0] >= s[0] && f[1] < s[1]);
   if(!up && !dn)
   {
      if(nearPips > 0)
      {
         bool near = MathAbs(f[1] - s[1]) <= nearPips * PIP;
         if(near && !nearFlag) AddSignal("heads_up", f[1] > s[1] ? -1 : 1, false, 0, "The two lines are within " + IntegerToString(nearPips) + " pips of each other.", bt);
         nearFlag = near;
      }
      return;
   }
   nearFlag = false;
   int side = up ? 1 : -1;
   lastCrossSide = side;
   closeWarned = false;
   // 1. the opposite trade closes (always, whatever Auto says)
   CloseOwn(up ? POSITION_TYPE_SELL : POSITION_TYPE_BUY, up ? "Closed: SMA 100 crossed back above SMA 5000." : "Closed: SMA 100 crossed back below SMA 5000.");
   // 2. a new trade, if allowed
   string why = "";
   if(!enabled) why = "Auto is off.";
   else if(paused) why = "All new trades are paused.";
   else if(!InSession()) why = "Outside trading hours (03:30 to 11:00 IST).";
   if(why != "")
   {
      AddSignal("skipped", side, false, 0, "SMA 100 crossed " + (up ? "above" : "below") + " SMA 5000. " + why, bt);
      return;
   }
   pendEntrySide = side; pendEntryUntil = TimeCurrent() + 300; pendEntryCandle = bt; pendWarned = false;
   TryEntry();
}

//+------------------------------------------------------------------+
//| commands from the dashboard                                      |
//+------------------------------------------------------------------+
bool InRange(double v, double lo, double hi, double step, double origin)
{
   if(v < lo - 1e-9 || v > hi + 1e-9) return false;
   double n = (v - origin) / step;
   return MathAbs(n - MathRound(n)) < 1e-6;
}

void ApplySettings(string cmdId, const string &payload)
{
   int rev = (int)StringToInteger(JRaw(payload, "settings_rev"));
   if(rev <= settingsRev) { AddResult(cmdId, "rejected", "Older settings revision."); return; }
   string st = JBlock(payload, "settings", '{', '}');
   double nl = nextLot, ml = maxLot; int tp = tpPips, sl = slPips, hs = hoursStart, he = hoursEnd, np = nearPips; bool uh = useHours;
   if(JHas(st, "next_lot")) nl = StringToDouble(JRaw(st, "next_lot"));
   if(JHas(st, "max_lot")) ml = StringToDouble(JRaw(st, "max_lot"));
   if(JHas(st, "take_profit_pips")) tp = (int)StringToInteger(JRaw(st, "take_profit_pips"));
   if(JHas(st, "stop_loss_pips")) sl = (int)StringToInteger(JRaw(st, "stop_loss_pips"));
   if(JHas(st, "hours_start_ist")) hs = (int)StringToInteger(JRaw(st, "hours_start_ist"));
   if(JHas(st, "hours_end_ist")) he = (int)StringToInteger(JRaw(st, "hours_end_ist"));
   if(JHas(st, "near_lines_pips")) np = (int)StringToInteger(JRaw(st, "near_lines_pips"));
   if(JHas(st, "use_trading_hours")) uh = (JRaw(st, "use_trading_hours") == "true");
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   string bad = "";
   if(!InRange(ml, vmin, 1.00, vstep, vmin)) bad = "Largest lot is outside its range.";
   else if(!InRange(nl, vmin, ml, vstep, vmin)) bad = "Next trade lot is outside its range (smallest " + D(vmin, 2) + ", largest allowed " + D(ml, 2) + ").";
   else if(!InRange(tp, 20, 1000, 10, 20)) bad = "Take profit is outside 20 to 1000 pips.";
   else if(!InRange(sl, 20, 500, 10, 20)) bad = "Stop loss is outside 20 to 500 pips.";
   else if(hs < 0 || hs > 1439 || he < 0 || he > 1439) bad = "Trading hours are outside the day.";
   else if(!InRange(np, 0, 200, 5, 0)) bad = "Heads-up distance is outside 0 to 200 pips.";
   if(bad != "") { AddResult(cmdId, "rejected", bad); return; }   // one bad value rejects the whole command
   nextLot = nl; maxLot = ml; tpPips = tp; slPips = sl; hoursStart = hs; hoursEnd = he; nearPips = np; useHours = uh; settingsRev = rev;
   SaveState();
   AddResult(cmdId, "applied", "");
}

void ApplySetLevels(string cmdId, const string &payload)
{
   ulong ticket = (ulong)StringToInteger(JRaw(payload, "position_id"));
   if(!PositionSelectByTicket(ticket) || !IsOwn(PositionGetString(POSITION_SYMBOL), PositionGetInteger(POSITION_MAGIC))) { AddResult(cmdId, "rejected", "That is not an open trade the bot owns."); return; }
   bool buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
   double curSl = PositionGetDouble(POSITION_SL), curTp = PositionGetDouble(POSITION_TP);
   double price = PositionGetDouble(POSITION_PRICE_CURRENT);
   int dg = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double sl = curSl, tp = curTp;
   if(JHas(payload, "sl"))
   {
      sl = NormalizeDouble(StringToDouble(JRaw(payload, "sl")), dg);
      if(curSl > 0 && (buy ? sl < curSl : sl > curSl)) { AddResult(cmdId, "rejected", "A stop can only move toward the price."); return; }
      if((buy ? price - sl : sl - price) <= 0.5) { AddResult(cmdId, "rejected", "The stop must stay on the losing side of the price."); return; }
   }
   if(JHas(payload, "tp"))
   {
      tp = NormalizeDouble(StringToDouble(JRaw(payload, "tp")), dg);
      if((buy ? tp - price : price - tp) <= 0.5) { AddResult(cmdId, "rejected", "The target must be on the winning side of the price."); return; }
   }
   if(trade.PositionModify(ticket, sl, tp) && trade.ResultRetcode() == TRADE_RETCODE_DONE) AddResult(cmdId, "applied", "");
   else AddResult(cmdId, "failed", "The broker refused it: " + trade.ResultRetcodeDescription());
}

bool TryManualClose(string cmdId, ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) { AddResult(cmdId, "applied", ""); return true; }     // already gone
   GlobalVariableSet("man_" + (string)ticket, 1);                                           // so the history says "manual"
   if(trade.PositionClose(ticket) && trade.ResultRetcode() == TRADE_RETCODE_DONE) { AddResult(cmdId, "applied", ""); return true; }
   lastError = trade.ResultRetcodeDescription();
   return false;
}

void RetryManualCloses(const string &serverTime)
{
   for(int i = ArraySize(mcCmd) - 1; i >= 0; i--)
   {
      bool done = TryManualClose(mcCmd[i], mcTicket[i]);
      bool expired = (!done && mcExpires[i] <= IsoSrv(TimeTradeServer()));
      if(done || expired)
      {
         if(expired) AddResult(mcCmd[i], "failed", "The broker refused it: " + lastError + ". The bot kept retrying until the command expired.");
         for(int j = i; j < ArraySize(mcCmd) - 1; j++) { mcCmd[j] = mcCmd[j + 1]; mcTicket[j] = mcTicket[j + 1]; mcExpires[j] = mcExpires[j + 1]; }
         ArrayResize(mcCmd, ArraySize(mcCmd) - 1); ArrayResize(mcTicket, ArraySize(mcTicket) - 1); ArrayResize(mcExpires, ArraySize(mcExpires) - 1);
      }
   }
}

void HandleCommand(const string &obj, string serverTime)
{
   string id = JRaw(obj, "command_id"), type = JRaw(obj, "type"), expires = JRaw(obj, "expires_at");
   if(id == "" || IsHandled(id)) return;
   if(expires <= serverTime) { AddResult(id, "expired", "It arrived after it expired."); MarkHandled(id); return; }
   string payload = JBlock(obj, "payload", '{', '}');
   if(type == "strategy.set_enabled")
   {
      if(JRaw(payload, "strategy_id") != "sma_cross") AddResult(id, "rejected", "Unknown strategy.");
      else { enabled = (JRaw(payload, "enabled") == "true"); SaveState(); AddResult(id, "applied", ""); }
   }
   else if(type == "bot.set_trading_paused") { paused = (JRaw(payload, "paused") == "true"); SaveState(); AddResult(id, "applied", ""); }
   else if(type == "strategy.update_settings") ApplySettings(id, payload);
   else if(type == "position.set_levels") ApplySetLevels(id, payload);
   else if(type == "position.close")
   {
      ulong ticket = (ulong)StringToInteger(JRaw(payload, "position_id"));
      if(!PositionSelectByTicket(ticket) || !IsOwn(PositionGetString(POSITION_SYMBOL), PositionGetInteger(POSITION_MAGIC))) AddResult(id, "rejected", "That is not an open trade the bot owns.");
      else if(!TryManualClose(id, ticket))
      {
         int n = ArraySize(mcCmd);                       // keep retrying every 10 seconds until the command expires
         ArrayResize(mcCmd, n + 1); ArrayResize(mcTicket, n + 1); ArrayResize(mcExpires, n + 1);
         mcCmd[n] = id; mcTicket[n] = ticket; mcExpires[n] = expires;
         MarkHandled(id);
         return;
      }
   }
   else AddResult(id, "rejected", "Unknown command.");
   MarkHandled(id);
}

//+------------------------------------------------------------------+
//| the report                                                       |
//+------------------------------------------------------------------+
string PositionsJson(double &floating)
{
   string out = ""; floating = 0;
   int dg = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      long magic = PositionGetInteger(POSITION_MAGIC);
      bool own = IsOwn(sym, magic);
      long id = PositionGetInteger(POSITION_IDENTIFIER);
      double sl = PositionGetDouble(POSITION_SL), slo = sl;
      if(own && GlobalVariableCheck("slo_" + (string)id)) slo = GlobalVariableGet("slo_" + (string)id);
      double profit = PositionGetDouble(POSITION_PROFIT), swap = PositionGetDouble(POSITION_SWAP), comm = 0;
      floating += profit + swap + comm;
      if(out != "") out += ",";
      out += "{\"position_id\":" + IntegerToString(id) + ",\"strategy_id\":" + (own ? "\"sma_cross\"" : "null") + ",\"magic\":" + IntegerToString(magic) + ",\"symbol\":\"" + sym + "\",\"side\":\"" + Side(PositionGetInteger(POSITION_TYPE)) +
             "\",\"volume\":" + D(PositionGetDouble(POSITION_VOLUME), 2) + ",\"volume_locked\":" + (own ? "true" : "false") + ",\"open_time\":\"" + IsoSrv((datetime)PositionGetInteger(POSITION_TIME)) +
             "\",\"open_price\":" + D(PositionGetDouble(POSITION_PRICE_OPEN), dg) + ",\"current_price\":" + D(PositionGetDouble(POSITION_PRICE_CURRENT), dg) +
             ",\"sl\":" + OrNull(sl, dg) + ",\"sl_original\":" + OrNull(slo, dg) + ",\"tp\":" + OrNull(PositionGetDouble(POSITION_TP), dg) +
             ",\"profit\":" + D(profit, 2) + ",\"swap\":" + D(swap, 2) + ",\"commission\":" + D(comm, 2) + "}";
   }
   return out;
}

string ClosedDealsJson()
{
   if(!HistorySelect(TimeCurrent() - 7 * 86400, TimeCurrent() + 86400)) return "";
   int n = HistoryDealsTotal();
   string out = ""; int count = 0;
   int dg = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   for(int i = 0; i < n && count < 40; i++)
   {
      ulong dt = HistoryDealGetTicket(i);
      long entry = HistoryDealGetInteger(dt, DEAL_ENTRY), type = HistoryDealGetInteger(dt, DEAL_TYPE);
      if((entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY) || (type != DEAL_TYPE_BUY && type != DEAL_TYPE_SELL)) continue;
      string closeIso = IsoSrv((datetime)HistoryDealGetInteger(dt, DEAL_TIME));
      if(closedThrough != "" && closeIso <= closedThrough) continue;
      long posId = HistoryDealGetInteger(dt, DEAL_POSITION_ID);
      double openPrice = 0, comm = HistoryDealGetDouble(dt, DEAL_COMMISSION), swap = HistoryDealGetDouble(dt, DEAL_SWAP);
      datetime openTime = 0; long magic = 0; string sym = HistoryDealGetString(dt, DEAL_SYMBOL);
      for(int j = 0; j < n; j++)
      {
         ulong d2 = HistoryDealGetTicket(j);
         if(HistoryDealGetInteger(d2, DEAL_POSITION_ID) != posId || HistoryDealGetInteger(d2, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
         openPrice = HistoryDealGetDouble(d2, DEAL_PRICE); openTime = (datetime)HistoryDealGetInteger(d2, DEAL_TIME);
         magic = HistoryDealGetInteger(d2, DEAL_MAGIC); comm += HistoryDealGetDouble(d2, DEAL_COMMISSION);
      }
      if(openPrice <= 0 || openTime >= (datetime)HistoryDealGetInteger(dt, DEAL_TIME)) continue;
      long reason = HistoryDealGetInteger(dt, DEAL_REASON);
      string why = "other";
      if(reason == DEAL_REASON_SL) why = "stop_loss";
      else if(reason == DEAL_REASON_TP) why = "take_profit";
      else if(reason == DEAL_REASON_SO) why = "stop_out";
      else if(reason == DEAL_REASON_EXPERT) why = GlobalVariableCheck("man_" + (string)posId) ? "manual" : "bot";
      else if(reason == DEAL_REASON_CLIENT || reason == DEAL_REASON_MOBILE || reason == DEAL_REASON_WEB) why = "manual";
      bool own = (magic == InpMagic && sym == _Symbol);
      if(out != "") out += ",";
      out += "{\"deal_id\":" + IntegerToString((long)dt) + ",\"position_id\":" + IntegerToString(posId) + ",\"strategy_id\":" + (own ? "\"sma_cross\"" : "null") + ",\"magic\":" + IntegerToString(magic) +
             ",\"symbol\":\"" + sym + "\",\"side\":\"" + (type == DEAL_TYPE_SELL ? "buy" : "sell") + "\",\"volume\":" + D(HistoryDealGetDouble(dt, DEAL_VOLUME), 2) +
             ",\"open_time\":\"" + IsoSrv(openTime) + "\",\"close_time\":\"" + closeIso + "\",\"open_price\":" + D(openPrice, dg) + ",\"close_price\":" + D(HistoryDealGetDouble(dt, DEAL_PRICE), dg) +
             ",\"profit\":" + D(HistoryDealGetDouble(dt, DEAL_PROFIT), 2) + ",\"commission\":" + D(comm, 2) + ",\"swap\":" + D(swap, 2) + ",\"close_reason\":\"" + why + "\"}";
      count++;
   }
   return out;
}

string BarsJson()
{
   MqlRates r[];
   int got;
   if(barsThrough == "") got = CopyRates(_Symbol, PERIOD_M1, 1, InpHistoryBars, r);
   else
   {
      string s = barsThrough; StringReplace(s, "-", "."); StringReplace(s, "T", " "); StringReplace(s, "Z", "");
      datetime from = StringToTime(s) + (datetime)GmtOffset() + 1;
      got = CopyRates(_Symbol, PERIOD_M1, from, TimeCurrent(), r);
   }
   if(got <= 0) return "";
   int dg = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   datetime forming = iTime(_Symbol, PERIOD_M1, 0);
   string out = ""; int sent = 0;
   for(int i = 0; i < got && sent < 1000; i++)
   {
      if(r[i].time >= forming) break;                      // only closed candles
      if(out != "") out += ",";
      out += "{\"t\":\"" + IsoSrv(r[i].time) + "\",\"o\":" + D(r[i].open, dg) + ",\"h\":" + D(r[i].high, dg) + ",\"l\":" + D(r[i].low, dg) + ",\"c\":" + D(r[i].close, dg) + ",\"v\":" + IntegerToString((long)r[i].tick_volume) + "}";
      sent++;
   }
   return out;
}

void SendReport()
{
   seq++;
   double floating;
   string pos = PositionsJson(floating);
   int own = OwnCount();
   string state = own > 0 ? "in_position" : ((enabled && !paused) ? "idle" : "paused");
   double bal = AccountInfoDouble(ACCOUNT_BALANCE), eq = AccountInfoDouble(ACCOUNT_EQUITY), mg = AccountInfoDouble(ACCOUNT_MARGIN), ml = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   string modeTxt = mode == ACCOUNT_TRADE_MODE_REAL ? "real" : (mode == ACCOUNT_TRADE_MODE_CONTEST ? "contest" : "demo");
   string sigs = "", res = "";
   for(int i = 0; i < ArraySize(sigQ); i++) sigs += (i ? "," : "") + sigQ[i];
   for(int i = 0; i < ArraySize(resQ); i++) res += (i ? "," : "") + resQ[i];
   string json = "{\"schema_version\":\"0.2\",\"sent_at\":\"" + NowIso() + "\",\"seq\":" + (string)seq + ",\"boot_id\":\"" + bootId + "\",\"bot\":{\"version\":\"" + BOT_VERSION + "\",\"platform\":\"MT5\",\"platform_build\":" + IntegerToString(TerminalInfoInteger(TERMINAL_BUILD)) + "}," +
      "\"account\":{\"login\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ",\"server\":\"" + JEsc(AccountInfoString(ACCOUNT_SERVER)) + "\",\"currency\":\"" + AccountInfoString(ACCOUNT_CURRENCY) + "\",\"mode\":\"" + modeTxt + "\",\"margin_mode\":\"" +
      (AccountInfoInteger(ACCOUNT_MARGIN_MODE) == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING ? "hedging" : "netting") + "\",\"leverage\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LEVERAGE)) + "}," +
      "\"snapshot\":{\"balance\":" + D(bal, 2) + ",\"equity\":" + D(eq, 2) + ",\"margin\":" + D(mg, 2) + ",\"free_margin\":" + D(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2) + ",\"margin_level\":" + (mg > 0 ? D(ml, 1) : "null") + ",\"floating_pl\":" + D(AccountInfoDouble(ACCOUNT_PROFIT), 2) + "}," +
      "\"trading_paused\":" + (paused ? "true" : "false") + ",\"strategies\":[{\"id\":\"sma_cross\",\"version\":\"0.1.0\",\"magic\":" + IntegerToString(InpMagic) + ",\"enabled\":" + (enabled ? "true" : "false") + ",\"state\":\"" + state + "\",\"settings_rev\":" + IntegerToString(settingsRev) +
      ",\"symbols\":[\"" + _Symbol + "\"],\"error\":null}],\"open_positions\":[" + pos + "],\"closed_deals\":[" + ClosedDealsJson() + "],\"signals\":[" + sigs + "],\"bars\":[" + BarsJson() + "],\"command_results\":[" + res + "]}";

   char data[], result[];
   string rh;
   StringToCharArray(json, data, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(data, ArraySize(data) - 1);
   string headers = "Content-Type: application/json\r\nX-Bot-Key: " + BotKey + "\r\n";
   ResetLastError();
   int code = WebRequest("POST", ServerUrl + "/v1/report", headers, 3000, data, result, rh);
   if(code != 200)
   {
      int err = GetLastError();
      if(code == -1 && err == 4014) Print("Bot Console: add ", ServerUrl, " under Tools > Options > Expert Advisors > Allow WebRequest.");
      else Print("Bot Console: report failed, http ", code, " error ", err, " ", CharArrayToString(result, 0, 200, CP_UTF8));
      backoffS = MathMin(60, backoffS * 2);
      nextReportTick = GetTickCount() + backoffS * 1000;
      return;
   }
   backoffS = InpReportSeconds;
   nextReportTick = GetTickCount() + InpReportSeconds * 1000;
   string resp = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(sigQ, 0);
   string ct = JRaw(resp, "closed_through"), bt = JRaw(resp, "bars_through");
   if(ct != "") closedThrough = ct;
   if(bt != "") barsThrough = bt;
   string acks = JBlock(resp, "command_results", '[', ']');
   for(int i = ArraySize(resQ) - 1; i >= 0; i--)
      if(StringFind(acks, resIds[i]) >= 0)
      {
         for(int j = i; j < ArraySize(resQ) - 1; j++) { resQ[j] = resQ[j + 1]; resIds[j] = resIds[j + 1]; }
         ArrayResize(resQ, ArraySize(resQ) - 1); ArrayResize(resIds, ArraySize(resIds) - 1);
      }
   string serverTime = JRaw(resp, "server_time");
   string cmds = JBlock(resp, "commands", '[', ']');
   int p = 0;
   while(true)                                           // each {...} in the commands array
   {
      int s = StringFind(cmds, "{", p);
      if(s < 0) break;
      int depth = 0, e = s;
      for(; e < StringLen(cmds); e++)
      {
         ushort c = StringGetCharacter(cmds, e);
         if(c == '{') depth++;
         else if(c == '}') { depth--; if(depth == 0) break; }
      }
      HandleCommand(StringSubstr(cmds, s, e - s + 1), serverTime);
      p = e + 1;
   }
}

//+------------------------------------------------------------------+
int OnInit()
{
   hFast = iMA(_Symbol, PERIOD_M1, 100, 0, MODE_SMA, PRICE_CLOSE);
   hSlow = iMA(_Symbol, PERIOD_M1, 5000, 0, MODE_SMA, PRICE_CLOSE);
   if(hFast == INVALID_HANDLE || hSlow == INVALID_HANDLE) { Print("Failed to create the SMA indicators"); return INIT_FAILED; }
   if(StringLen(BotKey) < 8) Print("Bot Console: BotKey is empty. Reports will be refused.");
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(50);
   MathSrand((int)(TimeLocal() ^ GetTickCount()));
   bootId = StringFormat("%08x%08x", MathRand() * 32768 + MathRand(), (int)TimeLocal());
   LoadState();
   // After a restart: take the side of the current regime, so a trade against it is closed and none opens late.
   double f[1], s[1];
   if(CopyBuffer(hFast, 0, 1, 1, f) == 1 && CopyBuffer(hSlow, 0, 1, 1, s) == 1) lastCrossSide = (f[0] > s[0]) ? 1 : -1;
   lastBarTime = iTime(_Symbol, PERIOD_M1, 0);
   EventSetTimer(1);
   PrintFormat("Bot Console EA %s started on %s, magic %d, report every %ds to %s", BOT_VERSION, _Symbol, (int)InpMagic, InpReportSeconds, ServerUrl);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   if(hFast != INVALID_HANDLE) IndicatorRelease(hFast);
   if(hSlow != INVALID_HANDLE) IndicatorRelease(hSlow);
}

void OnTick() { CheckNewBar(); }

void OnTimer()
{
   CheckNewBar();
   uint now = GetTickCount();
   if(now - lastRetry >= 10000)
   {
      lastRetry = now;
      EnforceCross();
      RetryManualCloses("");
   }
   if((int)(now - nextReportTick) >= 0) SendReport();
}
//+------------------------------------------------------------------+
