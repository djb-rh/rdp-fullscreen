local f = io.open("ports.txt","w")
for tag, port in pairs(manager.machine.ioport.ports) do
  f:write("PORT " .. tag .. "\n")
  for name, fld in pairs(port.fields) do
    f:write(string.format("   %-28s type=%-14s mask=%04X def=%d min=%d max=%d\n",
      name, tostring(fld.type), fld.mask, fld.defvalue, fld.minvalue or -1, fld.maxvalue or -1))
  end
end
f:close()
print("ports written")
manager.machine:exit()
