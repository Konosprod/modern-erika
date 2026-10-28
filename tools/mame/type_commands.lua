-- Frappe caractère par caractère (le jeu perd les touches envoyées trop vite)
local script = {
  {8, "\r"}, {16, "\r"},
  {30, "KOWIPI SIRABERU\r"},
  {42, "SOUZI NAGURU\r"},
  {54, "HOGEHOGE\r"},
  {66, "KAWUDO SIRABERU\r"},
}
local shots = {77, 84}
local RATE = 0.2
local k, s, queue, next_key = 1, 1, "", 0
emu.register_periodic(function()
  local t = manager.machine.time.seconds
  if k <= #script and t >= script[k][1] then
    queue = queue .. script[k][2]; k = k + 1
  end
  if #queue > 0 and t >= next_key then
    manager.machine.natkeyboard:post(queue:sub(1, 1))
    queue = queue:sub(2); next_key = t + RATE
  end
  if s <= #shots and t >= shots[s] then
    manager.machine.video:snapshot(); s = s + 1
  end
end)
