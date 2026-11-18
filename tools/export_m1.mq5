//+------------------------------------------------------------------+
//| export_m1.mq5                                                    |
//| Dumps every 1-minute bar of the tester symbol before the test    |
//| start date into a CSV in the shared "Common\Files" folder.       |
//|                                                                  |
//| How to use: run it once in the Strategy Tester with a very short |
//| date range (the bars BEFORE FromDate are what get exported).     |
//| It writes the file in OnInit and then deliberately fails init so |
//| the tester stops at once. It never places an order.              |
//+------------------------------------------------------------------+
#property copyright "Bot Console"
#property version   "1.00"

input datetime InpFrom = D'2024.01.01 00:00';   // first bar to export
input string   InpFile = "xauusd_m1.csv";       // file name in Common\Files

int OnInit()
{
   MqlRates r[];
   datetime to = TimeCurrent();
   int n = CopyRates(_Symbol, PERIOD_M1, InpFrom, to, r);   // oldest bar first
   PrintFormat("export_m1: %s, asked %s .. %s, got %d bars, server-GMT offset now %d s",
               _Symbol, TimeToString(InpFrom), TimeToString(to), n, (int)(TimeCurrent() - TimeGMT()));
   if(n <= 0)
      return INIT_FAILED;

   int h = FileOpen(InpFile, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(h == INVALID_HANDLE)
   {
      PrintFormat("export_m1: cannot open %s, error %d", InpFile, GetLastError());
      return INIT_FAILED;
   }
   FileWrite(h, "time", "open", "high", "low", "close", "tick_volume", "spread");
   for(int i = 0; i < n; i++)
      FileWrite(h,
                TimeToString(r[i].time, TIME_DATE | TIME_SECONDS),
                DoubleToString(r[i].open,  _Digits),
                DoubleToString(r[i].high,  _Digits),
                DoubleToString(r[i].low,   _Digits),
                DoubleToString(r[i].close, _Digits),
                (string)r[i].tick_volume,
                (string)r[i].spread);
   FileClose(h);
   PrintFormat("export_m1: wrote %d bars, first %s, last %s",
               n, TimeToString(r[0].time, TIME_DATE | TIME_SECONDS), TimeToString(r[n - 1].time, TIME_DATE | TIME_SECONDS));
   return INIT_FAILED;   // stop the tester now; nothing else to do
}

void OnTick() {}
