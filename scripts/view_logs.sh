#!/bin/bash
# AgenticGram Log Viewer
# Script para monitorear los logs del bot en tiempo real

echo "🔍 AgenticGram Log Viewer"
echo "=========================="
echo ""

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Función para mostrar el menú
show_menu() {
    echo "Selecciona una opción:"
    echo "1) Ver logs en tiempo real (tail -f)"
    echo "2) Ver últimas 50 líneas"
    echo "3) Ver últimas 100 líneas"
    echo "4) Buscar errores (ERROR/WARNING)"
    echo "5) Ver solo output de Claude"
    echo "6) Ver estadísticas de streaming"
    echo "7) Salir"
    echo ""
    read -p "Opción: " option
}

# Detectar ubicación de logs
detect_log_file() {
    # Buscar en ubicaciones comunes
    if [ -f "/var/log/agenticgram.log" ]; then
        echo "/var/log/agenticgram.log"
    elif [ -f "$HOME/AgenticGram/agenticgram.log" ]; then
        echo "$HOME/AgenticGram/agenticgram.log"
    elif [ -f "./agenticgram.log" ]; then
        echo "./agenticgram.log"
    else
        # Intentar encontrar usando journalctl
        if systemctl is-active --quiet agenticgram; then
            echo "JOURNALCTL"
        else
            echo "NOT_FOUND"
        fi
    fi
}

LOG_FILE=$(detect_log_file)

if [ "$LOG_FILE" == "NOT_FOUND" ]; then
    echo -e "${RED}❌ No se encontró el archivo de logs${NC}"
    echo ""
    echo "Opciones:"
    echo "1. Si el bot está corriendo, ejecuta: python -m src.bot"
    echo "2. Verifica la configuración LOG_FILE en config/.env"
    echo "3. Si usas systemd: sudo journalctl -u agenticgram -f"
    exit 1
fi

if [ "$LOG_FILE" == "JOURNALCTL" ]; then
    echo -e "${GREEN}✓ Bot detectado como servicio systemd${NC}"
    USE_JOURNALCTL=true
else
    echo -e "${GREEN}✓ Logs encontrados en: $LOG_FILE${NC}"
    USE_JOURNALCTL=false
fi

echo ""

# Loop principal
while true; do
    show_menu
    
    case $option in
        1)
            echo -e "${YELLOW}Mostrando logs en tiempo real... (Ctrl+C para salir)${NC}"
            echo ""
            if [ "$USE_JOURNALCTL" = true ]; then
                sudo journalctl -u agenticgram -f
            else
                tail -f "$LOG_FILE"
            fi
            ;;
        2)
            echo -e "${YELLOW}Últimas 50 líneas:${NC}"
            echo ""
            if [ "$USE_JOURNALCTL" = true ]; then
                sudo journalctl -u agenticgram -n 50
            else
                tail -n 50 "$LOG_FILE"
            fi
            echo ""
            read -p "Presiona Enter para continuar..."
            ;;
        3)
            echo -e "${YELLOW}Últimas 100 líneas:${NC}"
            echo ""
            if [ "$USE_JOURNALCTL" = true ]; then
                sudo journalctl -u agenticgram -n 100
            else
                tail -n 100 "$LOG_FILE"
            fi
            echo ""
            read -p "Presiona Enter para continuar..."
            ;;
        4)
            echo -e "${YELLOW}Buscando errores y warnings...${NC}"
            echo ""
            if [ "$USE_JOURNALCTL" = true ]; then
                sudo journalctl -u agenticgram | grep -E "ERROR|WARNING" | tail -n 50
            else
                grep -E "ERROR|WARNING" "$LOG_FILE" | tail -n 50
            fi
            echo ""
            read -p "Presiona Enter para continuar..."
            ;;
        5)
            echo -e "${YELLOW}Output de Claude (últimas 50 líneas):${NC}"
            echo ""
            if [ "$USE_JOURNALCTL" = true ]; then
                sudo journalctl -u agenticgram | grep -E "\[Line [0-9]+\]|Claude output" | tail -n 50
            else
                grep -E "\[Line [0-9]+\]|Claude output" "$LOG_FILE" | tail -n 50
            fi
            echo ""
            read -p "Presiona Enter para continuar..."
            ;;
        6)
            echo -e "${YELLOW}Estadísticas de streaming:${NC}"
            echo ""
            if [ "$USE_JOURNALCTL" = true ]; then
                STREAM_UPDATES=$(sudo journalctl -u agenticgram | grep "Stream update #" | wc -l)
                CALLBACKS=$(sudo journalctl -u agenticgram | grep "Triggering stream callback" | wc -l)
                ERRORS=$(sudo journalctl -u agenticgram | grep "Message edit failed" | wc -l)
            else
                STREAM_UPDATES=$(grep "Stream update #" "$LOG_FILE" | wc -l)
                CALLBACKS=$(grep "Triggering stream callback" "$LOG_FILE" | wc -l)
                ERRORS=$(grep "Message edit failed" "$LOG_FILE" | wc -l)
            fi
            
            echo "Total de actualizaciones enviadas: $STREAM_UPDATES"
            echo "Total de callbacks activados: $CALLBACKS"
            echo "Errores de edición: $ERRORS"
            echo ""
            
            if [ $ERRORS -gt 0 ]; then
                echo -e "${RED}⚠️  Hay errores de edición. Últimos 5:${NC}"
                if [ "$USE_JOURNALCTL" = true ]; then
                    sudo journalctl -u agenticgram | grep "Message edit failed" | tail -n 5
                else
                    grep "Message edit failed" "$LOG_FILE" | tail -n 5
                fi
            fi
            
            echo ""
            read -p "Presiona Enter para continuar..."
            ;;
        7)
            echo "👋 Saliendo..."
            exit 0
            ;;
        *)
            echo -e "${RED}Opción inválida${NC}"
            sleep 1
            ;;
    esac
    
    clear
done
