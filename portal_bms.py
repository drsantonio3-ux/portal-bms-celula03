# --- EXTRAÇÃO DOCUMENTO FONTE (SOLICITAÇÃO / NEWSE) ---
                    s_prot_match = re.search(r"(CA\d+-\d+)", texto_sol_upper)
                    s_prot = s_prot_match.group(1) if s_prot_match else "NÃO CONSTA"

                    s_ship_match = re.search(r"(?:ORDEM|ORDER|SHIPMENT)[^\d]*(\d{8,12})", texto_sol_upper)
                    s_ship = s_ship_match.group(1) if s_ship_match else (re.search(r"\b(8\d{9})\b", texto_sol_limpo).group(1) if re.search(r"\b(8\d{9})\b", texto_sol_limpo) else "NÃO CONSTA")

                    s_centre = "NÃO CONSTA"
                    if "PRUDENTE" in texto_sol_upper or "CAMARGO" in texto_sol_upper:
                        s_centre = "A. C. CAMARGO / FUNDAÇÃO PRUDENTE"
                    elif "FUNDACAO PIO XII" in texto_sol_upper or "FUNDAÇÃO PIO XII" in texto_sol_upper:
                        s_centre = "FUNDACAO PIO XII"
                    elif "HOSPITAL SÃO LUCAS" in texto_sol_upper or "HOSPITAL SAO LUCAS" in texto_sol_upper:
                        s_centre = "HOSPITAL SAO LUCAS DA PUCRS"

                    s_cep_match = re.search(r"CEP[^\d]*(\d{5}-?\d{3})", texto_sol_upper)
                    s_addr = s_cep_match.group(1).replace("-", "") if s_cep_match else (re.search(r"\b(\d{8})\b", texto_sol_upper).group(1) if re.search(r"\b(\d{8})\b", texto_sol_upper) else "NÃO CONSTA")

                    s_pi = "NÃO CONSTA"
                    for medico in ["JAYR SCHMIDT", "FLAVIO AUGUSTO", "MARIZA SCHAAN"]:
                        if medico in texto_sol_upper:
                            s_pi = medico; break

                    # Limpeza de Seriais (Evitar contar CEP e Reference Numbers como Kits)
                    seriais_sol_brutos = re.findall(r"\b(\d{6,8})\b", texto_sol_upper)
                    seriais_sol = [s for s in seriais_sol_brutos if s not in [s_ship, s_addr, "11899681", "88630413"] and not s.startswith("906")]
                    s_qty = str(len(seriais_sol)) if len(seriais_sol) > 0 else "NÃO CONSTA"

                    # Extração Contextual de Lotes (NEWSE) - Procura antes da data DD/MM/YYYY
                    palavras_proibidas = {"QUANTITY", "VALIDADE", "LOTE", "MATERIAL", "BATCH", "CLIMATIZADA", "CAMARA", "AREA", "PORTAL", "ENDERECO", "CENTRO", "SOCIAL", "TELEFONE", "PACKING", "VERBO", "DIVINO", "RUA", "CHAC", "ANTONIO", "SAO", "PAULO", "BRASIL", "NA", "N/A", "NULL"}
                    
                    lotes_sol_contexto = re.findall(r'\b([A-Z0-9]{4,15})\s+\d{2}/\d{2}/\d{4}\b', texto_sol_limpo)
                    s_lotes_sol = [l for l in lotes_sol_contexto if l not in palavras_proibidas]
                    
                    if not s_lotes_sol: # Fallback caso fuja do padrão
                        padrao_lote = re.compile(r'\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9\.]+\b')
                        s_lotes_sol = [l for l in padrao_lote.findall(texto_sol_upper) if l not in palavras_proibidas and len(l) >= 4 and not l.startswith("CA") and not l.startswith("TE") and "SHIP" not in l and "PROTOCOL" not in l]
                    s_lotes_sol = list(dict.fromkeys(s_lotes_sol))

                    # --- EXTRAÇÃO DOCUMENTO VALIDADO (PACKING LIST) ---
                    p_prot_match = re.search(r"PROTOCOL NUMBER\s*[:\s]*([A-Z0-9\-\/]+)", texto_packing_upper)
                    if p_prot_match:
                        p_prot_raw = p_prot_match.group(1).split('/')[0].strip()
                        p_prot_match2 = re.search(r"(CA\d+-\d+)", p_prot_raw)
                        p_prot = p_prot_match2.group(1) if p_prot_match2 else p_prot_raw
                    else:
                        p_prot = "NÃO CONSTA"

                    p_ship_match = re.search(r"(?:DELIVERY NUMBER|SHIPMENT)\s*[:\s]*(\d{8,12})", texto_packing_upper)
                    p_ship = p_ship_match.group(1) if p_ship_match else "NÃO CONSTA"

                    p_centre = "NÃO CONSTA"
                    p_shipto_bloco = texto_packing_upper.split("SHIP TO")[-1] if "SHIP TO" in texto_packing_upper else texto_packing_upper
                    if "CAMARGO" in p_shipto_bloco or "PRUDENTE" in p_shipto_bloco:
                        p_centre = "A. C. CAMARGO / FUNDAÇÃO PRUDENTE"
                    elif "FUNDAÇÃO PIO XII" in p_shipto_bloco or "FUNDACAO PIO XII" in p_shipto_bloco:
                        p_centre = "FUNDACAO PIO XII"
                    elif "HOSPITAL SAO LUCAS" in p_shipto_bloco or "HOSPITAL SÃO LUCAS" in p_shipto_bloco:
                        p_centre = "HOSPITAL SAO LUCAS DA PUCRS"

                    p_cep_match = re.search(r"(\d{5}-?\d{3})", p_shipto_bloco)
                    p_addr = p_cep_match.group(1).replace("-", "") if p_cep_match else "NÃO CONSTA"

                    p_pi = "NÃO CONSTA"
                    for medico in ["JAYR SCHMIDT", "FLAVIO AUGUSTO", "MARIZA SCHAAN"]:
                        if medico in p_shipto_bloco or medico in texto_packing_upper:
                            p_pi = medico; break

                    p_qty_matches = re.findall(r"(\d+)\s*EA", texto_packing_upper)
                    p_qty = str(sum([int(q) for q in p_qty_matches])) if p_qty_matches else "NÃO CONSTA"

                    # Extração Contextual de Lotes (Packing List) - Procura antes de "X EA"
                    lotes_pack_contexto = re.findall(r'\b([A-Z0-9]{4,15})\s+\d+\s+EA\b', texto_packing_limpo)
                    p_lotes_packing = [l for l in lotes_pack_contexto if l not in palavras_proibidas]
                    
                    if not p_lotes_packing: # Fallback
                        padrao_lote = re.compile(r'\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9\.]+\b')
                        p_lotes_packing = [l for l in padrao_lote.findall(texto_packing_upper) if l not in palavras_proibidas and len(l) >= 4 and not l.startswith("CA") and not l.startswith("TE") and "SHIP" not in l and "PROTOCOL" not in l]
                    p_lotes_packing = list(dict.fromkeys(p_lotes_packing))

                    # Coleta de Seriais
                    seriais_packing = []
                    serial_matches = re.findall(r"SERIAL\s*NO\.?\s*\(([^)]+)\)", texto_packing_upper)
                    if serial_matches:
                        for bloco in serial_matches:
                            if "-" in bloco:
                                p_arr = bloco.split("-")
                                if len(p_arr) == 2 and p_arr[0].strip().isdigit() and p_arr[1].strip().isdigit():
                                    seriais_packing.extend([str(s) for s in range(int(p_arr[0]), int(p_arr[1]) + 1)])
                            elif "," in bloco:
                                seriais_packing.extend([s.strip() for s in bloco.split(",")])
                            else:
                                seriais_packing.append(bloco.strip())
                    else:
                        seriais_packing = re.findall(r"\b\d{6,8}\b", texto_packing_upper)

                    seriais_faltantes = [s for s in seriais_packing if s not in texto_sol_upper]
                    seriais_status_ok = len(seriais_faltantes) == 0 and len(seriais_packing) > 0

                    # Validação cruzada de lotes
                    lotes_conferem = False
                    if len(p_lotes_packing) > 0 and len(s_lotes_sol) > 0:
                        lotes_conferem = all(
                            any(lote_p.replace(".", "") in lote_s.replace(".", "") for lote_s in s_lotes_sol)
                            for lote_p in p_lotes_packing
                        )

                    # --- COMPARAÇÃO ESTRITA ---
                    dados_validacao = [
                        {
                            "Campo Validado": "Dados de Protocolo",
                            "Documento Fonte": s_prot,
                            "Documento Validado": p_prot,
                            "Status": "✅ Conforme" if s_prot != "NÃO CONSTA" and p_prot != "NÃO CONSTA" and (s_prot.replace("-","") in p_prot.replace("-","") or p_prot.replace("-","") in s_prot.replace("-","")) else "❌ Divergência",
                            "Observação": "Protocolos idênticos." if s_prot == p_prot else "Protocolos divergentes entre os documentos."
                        },
                        {
                            "Campo Validado": "Shipment Number",
                            "Documento Fonte": s_ship,
                            "Documento Validado": p_ship,
                            "Status": "✅ Conforme" if s_ship != "NÃO CONSTA" and s_ship == p_ship else "❌ Divergência",
                            "Observação": "Números de shipment idênticos." if s_ship == p_ship else "Divergência no shipment."
                        },
                        {
                            "Campo Validado": "Centre and Department Name",
                            "Documento Fonte": s_centre,
                            "Documento Validado": p_centre,
                            "Status": "✅ Conforme" if s_centre != "NÃO CONSTA" and s_centre == p_centre else "❌ Divergência",
                            "Observação": "Razão social avaliada." if s_centre == p_centre else "Divergência na razão social / centro."
                        },
                        {
                            "Campo Validado": "Depot site Address",
                            "Documento Fonte": s_addr,
                            "Documento Validado": p_addr,
                            "Status": "✅ Conforme" if s_addr != "NÃO CONSTA" and s_addr == p_addr else "❌ Divergência",
                            "Observação": "Endereço / CEP verificado." if s_addr == p_addr else "Divergência no endereço / CEP."
                        },
                        {
                            "Campo Validado": "Investigator Name",
                            "Documento Fonte": s_pi,
                            "Documento Validado": p_pi,
                            "Status": "✅ Conforme" if s_pi != "NÃO CONSTA" and s_pi == p_pi else "❌ Divergência",
                            "Observação": "Nome do investigador comparado." if s_pi == p_pi else "Divergência no nome do investigador."
                        },
                        {
                            "Campo Validado": "Total quantity in shipment",
                            "Documento Fonte": s_qty,
                            "Documento Validado": p_qty,
                            "Status": "✅ Conforme" if s_qty != "NÃO CONSTA" and s_qty == p_qty else "❌ Divergência",
                            "Observação": "Quantidade total avaliada." if s_qty == p_qty else "Divergência na quantidade total."
                        },
                        {
                            "Campo Validado": "Dados dos Produtos (Batch / Quantity / kit IDs)",
                            "Documento Fonte": f"Lotes: {', '.join(s_lotes_sol[:3])} | Seriais: {', '.join(seriais_sol)}",
                            "Documento Validado": f"Lotes: {', '.join(p_lotes_packing[:3])} | Seriais: {', '.join(seriais_packing)}",
                            "Status": "✅ Conforme" if s_qty == p_qty and seriais_status_ok and lotes_conferem else "❌ Divergência",
                            "Observação": "Lotes e seriais conferem." if (seriais_status_ok and lotes_conferem) else "Divergência crítica de lotes ou seriais entre os documentos."
                        }
                    ]
